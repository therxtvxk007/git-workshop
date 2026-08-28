"""What this machine can actually run, and what it therefore cannot.

The point of this module is to make "we could not run it" a first-class,
recorded outcome rather than a gap in a table. A benchmark that needs an
80GB GPU and a container runtime, on a machine with neither, is
``blocked_environment`` -- a fact worth writing down, and quite different from
``reproduction_failed``.

Probing is deliberately passive. Nothing here executes ``nvidia-smi``, starts a
container or shells out at all: it reads what the operating system already
exposes and checks whether the relevant executables are on the path. A probe
that runs third-party tooling to find out whether it can run third-party tooling
has already done the thing it was supposed to be deciding about.

For tests and for deterministic manifests, :class:`EnvironmentProbe` can be
constructed with fixed values instead of reading the host at all, so an
environment hash in a fixture never depends on the machine that ran it.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field

from pramaanx.benchmarks.schemas import (
    Blocker,
    BlockerCode,
    HardwareRequirements,
    SoftwareEnvironment,
)
from pramaanx.hashing import hash_file, hash_object
from pramaanx.schemas.base import PramaanModel

if TYPE_CHECKING:
    from collections.abc import Sequence

NVIDIA_DRIVER_PATH = Path("/proc/driver/nvidia/version")
"""Present exactly when an NVIDIA kernel driver is loaded. Reading it runs nothing."""

CONTAINER_RUNTIMES = ("docker", "podman", "apptainer", "singularity")


class HostDescription(PramaanModel):
    """A passive description of the machine, as observed."""

    system: str
    machine: str
    python_version: str
    container_runtime: str | None = None
    nvidia_driver_version: str | None = None
    gpu_present: bool = False
    cpu_count: int | None = None

    def describe(self) -> str:
        gpu = self.nvidia_driver_version or ("gpu" if self.gpu_present else "no-gpu")
        runtime = self.container_runtime or "no-container-runtime"
        return f"{self.system}/{self.machine} py{self.python_version} {runtime} {gpu}"


class EnvironmentReport(PramaanModel):
    """Whether this host satisfies a benchmark's declared requirements."""

    host: HostDescription
    environment_hash: str
    satisfied: bool
    blockers: list[Blocker] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "host": self.host.canonical_dict(),
            "host_description": self.host.describe(),
            "environment_hash": self.environment_hash,
            "satisfied": self.satisfied,
            "blockers": [blocker.canonical_dict() for blocker in self.blockers],
        }


def _read_nvidia_driver_version(path: Path = NVIDIA_DRIVER_PATH) -> str | None:
    """The driver version string, if the kernel exposes one.

    Errors are swallowed on purpose: on a machine without the driver this file
    is simply absent, and on a locked-down one it may exist but be unreadable.
    Neither is an error in the probe -- both mean "no usable GPU driver here".
    """
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip().splitlines()[0]
    except OSError:
        return None


def _detect_container_runtime(candidates: Sequence[str] = CONTAINER_RUNTIMES) -> str | None:
    """The first container runtime on the path. Looks only; does not invoke."""
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return None


class EnvironmentProbe:
    """Reads the host, or reports fixed values when given them.

    ``fixed`` exists so that manifests produced in tests and fixtures do not
    embed the CI runner's kernel version, which would make every recorded
    environment hash machine-specific and every reproducibility test a test of
    the runner.
    """

    def __init__(self, fixed: HostDescription | None = None) -> None:
        self._fixed = fixed

    def host(self) -> HostDescription:
        if self._fixed is not None:
            return self._fixed
        driver = _read_nvidia_driver_version()
        return HostDescription(
            system=platform.system(),
            machine=platform.machine(),
            python_version=platform.python_version(),
            container_runtime=_detect_container_runtime(),
            nvidia_driver_version=driver,
            gpu_present=driver is not None,
            cpu_count=os.cpu_count(),
        )

    def check(
        self,
        hardware: HardwareRequirements | None,
        software: SoftwareEnvironment | None,
    ) -> EnvironmentReport:
        """Compare declared requirements with what this host offers.

        Every shortfall becomes a blocker naming the requirement it failed, so a
        blocked benchmark can say *what* would unblock it rather than only that
        something did.
        """
        host = self.host()
        blockers: list[Blocker] = []

        if hardware is not None:
            if hardware.needs_gpu and not host.gpu_present:
                blockers.append(
                    Blocker(
                        field="hardware_requirements",
                        code=BlockerCode.COMPUTE_UNAVAILABLE,
                        detail=f"{hardware.gpu_count} GPU(s) required "
                        f"({hardware.gpu_model or 'unspecified model'}); no NVIDIA driver "
                        "is present on this host",
                    )
                )
            if (
                hardware.cpu_cores is not None
                and host.cpu_count is not None
                and host.cpu_count < hardware.cpu_cores
            ):
                blockers.append(
                    Blocker(
                        field="hardware_requirements",
                        code=BlockerCode.COMPUTE_UNAVAILABLE,
                        detail=f"{hardware.cpu_cores} CPU cores required, "
                        f"{host.cpu_count} available",
                    )
                )

        if software is not None:
            if software.container_image and host.container_runtime is None:
                blockers.append(
                    Blocker(
                        field="software_environment",
                        code=BlockerCode.ENVIRONMENT_UNAVAILABLE,
                        detail=f"image {software.container_image!r} is required but no "
                        f"container runtime ({', '.join(CONTAINER_RUNTIMES)}) is on the path",
                    )
                )
            if software.container_image and not software.is_pinned:
                blockers.append(
                    Blocker(
                        field="software_environment",
                        code=BlockerCode.MUTABLE_REFERENCE,
                        detail=f"image {software.container_image!r} is named by tag with no "
                        "digest; a tag can be repointed at different bytes",
                    )
                )

        return EnvironmentReport(
            host=host,
            environment_hash=environment_hash(hardware, software),
            satisfied=not blockers,
            blockers=blockers,
        )


def environment_hash(
    hardware: HardwareRequirements | None,
    software: SoftwareEnvironment | None,
) -> str:
    """Identity of a declared environment.

    Derived from what the contract *demands*, not from the host that happens to
    be reading it: two machines validating the same contract must agree, or the
    hash cannot be used to show that two runs shared an environment.
    """
    return hash_object(
        {
            "hardware": hardware.canonical_dict() if hardware else None,
            "software": software.canonical_dict() if software else None,
        }
    )


def package_lock_hash(lock_path: Path) -> str | None:
    """Hash the dependency lock file, so a run manifest pins its dependencies."""
    if not lock_path.exists():
        return None
    return hash_file(lock_path)


def interpreter_identity() -> dict[str, str]:
    """The running interpreter, for the record."""
    return {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "executable_stem": Path(sys.executable).name,
    }
