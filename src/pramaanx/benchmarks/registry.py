"""Loading, validating and writing the machine-readable benchmark registry.

The registry is a single YAML file plus one contract file per benchmark. YAML
because a benchmark contract is read and argued over by people far more often
than it is parsed, and a format nobody reads is a format nobody checks.

Loading is strict in both directions. An unknown field in a contract is an
error, not something ignored -- ``extra="forbid"`` on the models means a typo in
``official_commit`` cannot silently produce a contract with no commit. And a
duplicate ``benchmark_id`` is refused, because two records under one identifier
means every later lookup silently picks one of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import Field

from pramaanx.benchmarks.manifests import ManifestStore
from pramaanx.benchmarks.schemas import BenchmarkContract, BenchmarkStatus
from pramaanx.benchmarks.verification import ValidationReport, validate_contract
from pramaanx.hashing import canonical_json, hash_object
from pramaanx.schemas.base import PramaanModel

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

REGISTRY_VERSION = 1
DEFAULT_REGISTRY_PATH = Path("research/benchmarks/registry.yaml")
DEFAULT_CONTRACT_DIR = Path("research/benchmarks/contracts")
DEFAULT_REPRODUCTION_DIR = Path("research/benchmarks/reproductions")


class RegistryError(ValueError):
    """The registry file could not be loaded, or is internally inconsistent."""


class RegistryFileExistsError(FileExistsError):
    """A write would have replaced an existing registry artefact."""


class BenchmarkRegistry(PramaanModel):
    """Every benchmark this project has committed to, in one place.

    Includes the ones it is blocked on. A registry that lists only the
    benchmarks that went well is a marketing document, and the same argument
    that governs ``research/experiment_registry.yaml`` governs this one.
    """

    version: int = REGISTRY_VERSION
    contracts: list[BenchmarkContract] = Field(default_factory=list)

    def __iter__(self) -> Iterator[BenchmarkContract]:  # type: ignore[override]
        return iter(sorted(self.contracts, key=lambda contract: contract.benchmark_id))

    def __len__(self) -> int:
        return len(self.contracts)

    def ids(self) -> list[str]:
        return sorted(contract.benchmark_id for contract in self.contracts)

    def get(self, benchmark_id: str) -> BenchmarkContract:
        for contract in self.contracts:
            if contract.benchmark_id == benchmark_id:
                return contract
        raise KeyError(
            f"no benchmark {benchmark_id!r} in the registry; known ids: {', '.join(self.ids())}"
        )

    def by_status(self, status: BenchmarkStatus) -> list[BenchmarkContract]:
        return [contract for contract in self if contract.status is status]

    def by_family(self, family: str) -> list[BenchmarkContract]:
        return [contract for contract in self if contract.benchmark_family == family]

    def registry_hash(self) -> str:
        """Content identity of the whole registry, independent of file order."""
        return hash_object(sorted(contract.contract_hash() for contract in self.contracts))

    def validate_all(
        self,
        store: ManifestStore | None = None,
    ) -> dict[str, ValidationReport]:
        """Validate every contract, against its runs where a store is supplied."""
        reports: dict[str, ValidationReport] = {}
        for contract in self:
            runs = store.for_benchmark(contract.benchmark_id) if store else ()
            reports[contract.benchmark_id] = validate_contract(contract, runs)
        return reports


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RegistryError(f"registry file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RegistryError(f"{path} does not contain a YAML mapping")
    return loaded


def load_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    contract_dir: Path | None = None,
) -> BenchmarkRegistry:
    """Read the registry index and every contract it references.

    The index holds only identifiers and file references; the contracts live in
    their own files so that editing one benchmark produces a diff about that
    benchmark. A referenced contract file that is missing is an error rather than
    a skipped entry -- a registry that silently shrinks is worse than one that
    fails to load.
    """
    document = _read_yaml(path)
    version = document.get("version")
    if version != REGISTRY_VERSION:
        raise RegistryError(
            f"{path} declares registry version {version!r}; this code reads version "
            f"{REGISTRY_VERSION}"
        )
    root = contract_dir if contract_dir is not None else path.parent / "contracts"
    entries = document.get("benchmarks") or []
    if not isinstance(entries, list):
        raise RegistryError(f"{path}: 'benchmarks' must be a list")

    contracts: list[BenchmarkContract] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or "contract" not in entry:
            raise RegistryError(f"{path}: every benchmark entry needs a 'contract' file reference")
        contract_path = root / str(entry["contract"])
        contract = load_contract(contract_path)
        declared = entry.get("benchmark_id")
        if declared is not None and declared != contract.benchmark_id:
            raise RegistryError(
                f"{path} lists {declared!r} but {contract_path} defines {contract.benchmark_id!r}"
            )
        if contract.benchmark_id in seen:
            raise RegistryError(
                f"duplicate benchmark_id {contract.benchmark_id!r}; every later lookup "
                "would silently resolve to one of them"
            )
        seen.add(contract.benchmark_id)
        contracts.append(contract)
    return BenchmarkRegistry(version=REGISTRY_VERSION, contracts=contracts)


def load_contract(path: Path) -> BenchmarkContract:
    """Read one contract file, rejecting unknown fields."""
    if not path.exists():
        raise RegistryError(f"contract file not found: {path}")
    document = _read_yaml(path)
    try:
        return BenchmarkContract.model_validate(document)
    except Exception as error:
        raise RegistryError(f"{path}: {error}") from error


def write_contract(
    contract: BenchmarkContract,
    path: Path,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> Path:
    """Write a contract to YAML, refusing to clobber an existing file.

    ``overwrite`` exists for the deliberate edit of a contract that is already
    tracked; it is never set by the harness itself, which only ever creates.
    """
    if path.exists() and not overwrite:
        raise RegistryFileExistsError(
            f"{path} already exists; refusing to overwrite a contract. Edit it in place, "
            "or pass overwrite=True if replacing it is genuinely intended."
        )
    if dry_run:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_contract(contract), encoding="utf-8")
    return path


def dump_contract(contract: BenchmarkContract) -> str:
    """Render a contract as deterministic, readable YAML.

    Keys are sorted and the width is uncapped, so re-serialising an unchanged
    contract produces byte-identical output and a diff shows only real edits.
    """
    payload = contract.canonical_dict()
    return yaml.safe_dump(
        payload,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )


def dump_registry_index(contracts: Sequence[BenchmarkContract]) -> str:
    """Render the registry index that points at the contract files."""
    payload = {
        "version": REGISTRY_VERSION,
        "benchmarks": [
            {
                "benchmark_id": contract.benchmark_id,
                "contract": f"{contract.benchmark_id}.yaml",
                "status": contract.status.value,
                "family": contract.benchmark_family,
            }
            for contract in sorted(contracts, key=lambda item: item.benchmark_id)
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, width=100)


def registry_manifest(registry: BenchmarkRegistry) -> dict[str, Any]:
    """A machine-readable summary of the registry as it stands."""
    return {
        "version": registry.version,
        "registry_hash": registry.registry_hash(),
        "count": len(registry),
        "by_status": {
            status.value: len(registry.by_status(status))
            for status in BenchmarkStatus
            if registry.by_status(status)
        },
        "benchmarks": [
            {
                "benchmark_id": contract.benchmark_id,
                "task_name": contract.task_name,
                "family": contract.benchmark_family,
                "status": contract.status.value,
                "contract_hash": contract.contract_hash(),
                "blocker_count": len(contract.blockers),
            }
            for contract in registry
        ],
    }


def emit_json(payload: Any) -> str:
    """Canonical JSON, so two runs of the same command produce the same bytes."""
    return canonical_json(payload)
