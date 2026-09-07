"""The retrospective block, opened once.

A lockbox is a promise about the future made legible in the present: these
origins will be scored once, with this evaluation contract, using these models,
and nothing will be tuned afterwards. The mechanism is a seal over that
promise, and a receipt recording when it was kept.

Two things this is honest about (S33.2). A local hash seal detects a change; it
does not prevent the machine's owner from reading the data, so the guarantee is
"a modification is visible" and not "access is impossible". And a *failed*
opening must be resumable: a crash between reading the origins and writing the
report cannot be allowed to consume the one opportunity, so an open is
idempotent for the run that owns it and refused for any other.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import canonical_json, hash_object, utc_isoformat
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class LockboxSeal(VersionedModel):
    """What was promised, and the hash that makes a change visible."""

    name: str
    origins: tuple[UtcDatetime, ...]
    #: Hash of the frozen metric set, weights and eligibility rules.
    evaluation_contract: str
    #: Models permitted to be scored. A model absent here cannot be added after
    #: the block is opened, which is the substance of "no later tuning".
    permitted_models: tuple[str, ...] = ()
    sealed_at: UtcDatetime
    seal_hash: str = ""

    def fingerprint(self) -> dict[str, object]:
        return {
            "name": self.name,
            "origins": [utc_isoformat(origin) for origin in self.origins],
            "evaluation_contract": self.evaluation_contract,
            "permitted_models": sorted(self.permitted_models),
        }

    def with_hash(self) -> LockboxSeal:
        return self.model_copy(update={"seal_hash": hash_object(self.fingerprint())})

    def verify(self) -> None:
        if self.seal_hash != hash_object(self.fingerprint()):
            raise ContractViolationError(
                "the lockbox seal does not match its contents; the block was "
                "modified after sealing",
                name=self.name,
            )


class LockboxReceipt(VersionedModel):
    """Proof the block was opened, by whom, and for what."""

    seal_hash: str
    run_id: str
    opened_at: UtcDatetime
    report_hash: str = ""


class Lockbox:
    """One sealed block on disk, with an opening receipt beside it."""

    def __init__(self, root: Path, *, clock: Clock | None = None) -> None:
        self.root = Path(root)
        self.clock = clock or SystemClock()

    def _seal_path(self, name: str) -> Path:
        return self.root / f"{name}.seal.json"

    def _receipt_path(self, name: str) -> Path:
        return self.root / f"{name}.receipt.json"

    def seal(
        self,
        name: str,
        *,
        origins: tuple[datetime, ...],
        evaluation_contract: str,
        permitted_models: tuple[str, ...] = (),
    ) -> LockboxSeal:
        """Seal a block. Re-sealing an existing name is refused."""
        path = self._seal_path(name)
        if path.exists():
            raise ContractViolationError(
                "this lockbox is already sealed; re-sealing would replace the promise it recorded",
                name=name,
            )
        seal = LockboxSeal(
            name=name,
            origins=origins,
            evaluation_contract=evaluation_contract,
            permitted_models=tuple(sorted(permitted_models)),
            sealed_at=self.clock.now(),
        ).with_hash()
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(seal.model_dump(mode="json")), encoding="utf-8")
        return seal

    def load(self, name: str) -> LockboxSeal:
        path = self._seal_path(name)
        if not path.exists():
            raise ContractViolationError("no such lockbox", name=name)
        seal = LockboxSeal.model_validate_json(path.read_text(encoding="utf-8"))
        seal.verify()
        return seal

    def is_open(self, name: str) -> bool:
        return self._receipt_path(name).exists()

    def receipt(self, name: str) -> LockboxReceipt:
        path = self._receipt_path(name)
        if not path.exists():
            raise ContractViolationError("this lockbox has not been opened", name=name)
        return LockboxReceipt.model_validate_json(path.read_text(encoding="utf-8"))

    def open(self, name: str, *, run_id: str) -> LockboxReceipt:
        """Authorise the one evaluation, or resume the one already authorised.

        A second run asking to open the same block is refused. The *same* run
        asking again gets its receipt back, so a crash between authorisation
        and the report does not burn the opportunity.
        """
        seal = self.load(name)
        if self.is_open(name):
            existing = self.receipt(name)
            if existing.run_id != run_id:
                raise ContractViolationError(
                    "this lockbox was already opened by another run; a second "
                    "evaluation of a sealed block is tuning, not testing",
                    name=name,
                    opened_by=existing.run_id,
                    opened_at=utc_isoformat(existing.opened_at),
                )
            return existing

        receipt = LockboxReceipt(
            seal_hash=seal.seal_hash, run_id=run_id, opened_at=self.clock.now()
        )
        self._receipt_path(name).write_text(
            canonical_json(receipt.model_dump(mode="json")), encoding="utf-8"
        )
        return receipt

    def record_report(self, name: str, *, run_id: str, report_hash: str) -> LockboxReceipt:
        """Attach the produced report to the opening. Re-reading is allowed."""
        receipt = self.open(name, run_id=run_id)
        if receipt.report_hash and receipt.report_hash != report_hash:
            raise ContractViolationError(
                "a different report was already recorded against this opening",
                name=name,
                recorded=receipt.report_hash,
                offered=report_hash,
            )
        updated = receipt.model_copy(update={"report_hash": report_hash})
        self._receipt_path(name).write_text(
            canonical_json(updated.model_dump(mode="json")), encoding="utf-8"
        )
        return updated

    def permits(self, name: str, model_id: str) -> bool:
        seal = self.load(name)
        return not seal.permitted_models or model_id in seal.permitted_models

    def manifest(self) -> dict[str, object]:
        """Every sealed block and whether it has been opened."""
        blocks = []
        for path in sorted(self.root.glob("*.seal.json")):
            name = path.name.removesuffix(".seal.json")
            entry: dict[str, object] = {"name": name, "opened": self.is_open(name)}
            if entry["opened"]:
                entry["opened_by"] = json.loads(
                    self._receipt_path(name).read_text(encoding="utf-8")
                )["run_id"]
            blocks.append(entry)
        return {"lockboxes": blocks}


class RoleSeparation(VersionedModel):
    """Which origins each stage may touch. Read by the runtime, not by a model."""

    select_origins: tuple[UtcDatetime, ...] = Field(default_factory=tuple)
    calibrate_origins: tuple[UtcDatetime, ...] = Field(default_factory=tuple)
    test_origins: tuple[UtcDatetime, ...] = Field(default_factory=tuple)

    def check_disjoint(self) -> None:
        """Calibration origins disjoint from selection and test origins (S13)."""
        select = {utc_isoformat(item) for item in self.select_origins}
        calibrate = {utc_isoformat(item) for item in self.calibrate_origins}
        test = {utc_isoformat(item) for item in self.test_origins}
        for left, right, names in (
            (select, calibrate, ("select", "calibrate")),
            (select, test, ("select", "test")),
            (calibrate, test, ("calibrate", "test")),
        ):
            overlap = sorted(left & right)
            if overlap:
                raise ContractViolationError(
                    "origin sets overlap across roles",
                    roles=list(names),
                    origins=overlap[:5],
                )
