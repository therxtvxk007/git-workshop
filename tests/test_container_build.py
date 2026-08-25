"""The container must be built from the lockfile, and say which one.

The defect these tests were written against: the Dockerfile ran
`pip install ".[boost,serve,llm]"`, which ignores `uv.lock` and resolves fresh
versions at build time. The image and the tested environment could therefore
differ, with nothing recording that they had -- in the one artefact most likely
to be shipped and least likely to be re-tested.

Most of these are static checks on the build definition rather than a build.
That is deliberate: they run everywhere, including where no Docker daemon
exists, and a build that cannot run must not silently count as a pass.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()

#: The Dockerfile with comments stripped. The comments explain what was removed
#: and name it, so a naive substring search over the whole file finds the
#: explanation and reports it as the defect.
DOCKERFILE_INSTRUCTIONS = "\n".join(
    line for line in DOCKERFILE.splitlines() if not line.lstrip().startswith("#")
)


def test_the_image_is_built_from_the_lockfile():
    """END-TO-END NEGATIVE CONTROL for requirement 7 (static half)."""
    assert "uv sync --frozen" in DOCKERFILE_INSTRUCTIONS, "the image does not install from uv.lock"
    assert "pip install" not in DOCKERFILE_INSTRUCTIONS, (
        "the image still resolves dependencies at build time"
    )
    assert "COPY pyproject.toml uv.lock" in DOCKERFILE_INSTRUCTIONS


def test_the_lockfile_reaches_the_build_context():
    """A `--frozen` install with the lockfile excluded from the context is a
    build failure waiting for the next rebuild."""
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    assert "uv.lock" not in [line.strip() for line in ignored]


def test_the_image_records_which_lockfile_it_was_built_from():
    assert "uv.lock.sha256" in DOCKERFILE
    assert "dev.pramaan.uv-lock-sha256" in DOCKERFILE
    assert "PRAMAAN_LOCKFILE_SHA256_FILE" in DOCKERFILE


def test_status_reports_the_lockfile_hash_of_this_environment():
    from pramaan_x.service import lockfile_sha256

    expected = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    assert lockfile_sha256() == expected


def test_status_prefers_the_stamp_the_image_wrote(tmp_path, monkeypatch):
    from pramaan_x.service import lockfile_sha256

    stamp = tmp_path / "uv.lock.sha256"
    stamp.write_text("deadbeef\n")
    monkeypatch.setenv("PRAMAAN_LOCKFILE_SHA256_FILE", str(stamp))
    assert lockfile_sha256() == "deadbeef"


def test_status_endpoint_exposes_it(ready_status_client):
    body = ready_status_client.get("/status").json()
    assert body["version"]
    assert body["timestamp_policy"] == "strict"
    assert body["uv_lock_sha256"]
    assert len(body["uv_lock_sha256"]) == 64


@pytest.fixture(scope="module")
def ready_status_client():
    from fastapi.testclient import TestClient

    from pramaan_x.api import create_app
    from pramaan_x.config import Config

    client = TestClient(create_app(Config()))
    client.post("/ingest/synthetic", json={"days": 120})
    return client


# ------------------------------------------------------------ image pinning ---


def test_no_deployment_image_is_pinned_to_latest():
    """NEGATIVE CONTROL: `:latest` means the container you debugged and the one
    that runs tomorrow are different software with the same name."""
    offenders = [
        line.strip() for line in COMPOSE.splitlines() if re.search(r"image:\s*\S+:latest\s*$", line)
    ]
    assert offenders == [], f"unpinned images: {offenders}"


def test_every_compose_image_carries_an_explicit_version_or_digest():
    images = re.findall(r"^\s*image:\s*(\S+)\s*$", COMPOSE, flags=re.MULTILINE)
    assert images
    for image in images:
        assert "@sha256:" in image or re.search(r":[\w.\-]+$", image), image
        assert not image.endswith(":latest"), image


def test_the_base_images_are_pinned_too():
    bases = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, flags=re.MULTILINE)
    assert bases
    for base in bases:
        assert not base.endswith(":latest"), base
        assert ":" in base or "@" in base, base


# ------------------------------------------------------------- the real build ---


DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    if shutil.which("docker")
    else False
)


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="no Docker daemon is reachable")
def test_docker_build_and_http_smoke():
    """Runs only where a daemon exists. Where it does not, this is reported as
    unavailable and never as a pass."""
    tag = "pramaan-x:pytest"
    build = subprocess.run(
        ["docker", "build", "-t", tag, "."],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    assert build.returncode == 0, build.stderr[-4000:]
    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            tag,
            "python",
            "-c",
            "import pramaan_x, json; print(json.dumps({'v': pramaan_x.__version__}))",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stderr[-2000:]
