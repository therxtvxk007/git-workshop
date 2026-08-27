"""A reproducible calibration sample drawn from the synthetic world.

Fitting a calibrator or a conformal risk controller needs a sample of
``(probability, outcome)`` pairs. Phase 2 records that it has none. It does:
the M0 demo produces 2,086 forecasts against a machine-derived outcome
registry, offline, in about twenty seconds.

Three properties make that sample usable rather than merely available.

*It is identical to what the backtest scores.* The pairs come from
:class:`~pramaanx.evaluation.backtest.ScoringResult`, which builds them in the
one place where the persisted forecasts and their match results are both in
hand. Re-deriving the labels here would risk a second, subtly different
definition of "did this forecast hit", and a calibrator fitted against the
wrong labels is worse than an uncalibrated one.

*It is portable.* This one needed care. ``Settings.config_hash`` hashes the
whole resolved settings model, ``storage.data_root`` included, so it changes
when the same evidence is generated under a different path. Snapshot hashes
fold in ``config_hash``, forecast identifiers derive from snapshot hashes, and
the scoring pass reads forecasts sorted by identifier -- so the *order* of the
pooled rows depends on where the data directory happens to live. The content
does not: the per-fold multiset of ``(probability, label)`` pairs is identical
across data roots, which this module verified before relying on it. Rows are
therefore canonically ordered within each fold, and nothing path-dependent
(no snapshot identifier, no ``config_hash``) enters the fingerprint. Pinning
those would have produced a fixture that only ever reproduced on one machine.

*It preserves fold boundaries.* Folds stay in cutoff order and
:class:`FoldSlice` records where each one starts and stops, so a caller can
split temporally -- fit on earlier cutoffs, validate on later ones. Conformal
prediction assumes exchangeability, which temporal data violates; a random
split would hide that violation, and a bound quoted from a hidden violation is
worse than no bound. :meth:`CalibrationSample.split_at_fold` is the honest
split, and it is the only one this module offers.

What this sample is **not**: real. The world is synthetic and its outcome
registry is unadjudicated, so it can exercise a fitter, expose a numerical bug
and support a regression test. It cannot tell anyone that a calibrator works
on real prose. :data:`SYNTHETIC_CAVEAT` travels with every sample so that
limitation cannot be quoted away.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pramaanx.evaluation.backtest import Backtester, load_experiment
from pramaanx.hashing import canonical_json, hash_object, utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.timeguard.snapshots import code_hash

log = get_logger(__name__)

#: Must accompany any number computed from this sample.
SYNTHETIC_CAVEAT = (
    "This sample comes from the seeded synthetic world with a machine-derived, "
    "unadjudicated outcome registry. It measures agreement with automated "
    "resolution, not with reality, and establishes nothing about real prose."
)

#: Manifest schema version. Bump when the pinned field set changes.
MANIFEST_VERSION = 1

#: Fields the manifest actually verifies. ``code_hash`` is deliberately absent:
#: it moves on every source edit, and a fixture that fails whenever unrelated
#: code changes would be re-pinned reflexively until it verified nothing.
_VERIFIED_FIELDS = (
    "manifest_version",
    "experiment",
    "rows",
    "positives",
    "folds",
    "cutoffs",
    "sample_fingerprint",
)


class FixtureDriftError(RuntimeError):
    """A regenerated fixture did not reproduce its pinned manifest."""


@dataclass(frozen=True)
class FoldSlice:
    """Where one cutoff's forecasts sit inside the pooled arrays.

    Identified by ``cutoff_at`` rather than by snapshot identifier: snapshot
    identifiers are path-dependent (see the module docstring), so carrying one
    here would invite a comparison that fails across machines for no reason.
    """

    cutoff_at: datetime
    start: int
    stop: int

    def __len__(self) -> int:
        return self.stop - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "cutoff_at": utc_isoformat(self.cutoff_at),
            "start": self.start,
            "stop": self.stop,
        }


@dataclass(frozen=True)
class CalibrationSample:
    """Pooled ``(probability, label)`` pairs plus the fold structure."""

    probabilities: tuple[float, ...]
    labels: tuple[int, ...]
    folds: tuple[FoldSlice, ...]
    experiment: str
    code_hash: str
    caveat: str = SYNTHETIC_CAVEAT

    def __post_init__(self) -> None:
        if len(self.probabilities) != len(self.labels):
            raise ValueError(
                f"{len(self.probabilities)} probabilities against "
                f"{len(self.labels)} labels: the pooled arrays are misaligned"
            )
        if any(label not in (0, 1) for label in self.labels):
            raise ValueError("labels must be 0 or 1")
        if any(not 0.0 <= p <= 1.0 for p in self.probabilities):
            raise ValueError("probabilities must lie in [0, 1]")
        covered = sum(len(fold) for fold in self.folds)
        if covered != len(self.labels):
            raise ValueError(
                f"fold slices cover {covered} rows but the sample holds {len(self.labels)}"
            )

    def __len__(self) -> int:
        return len(self.labels)

    @property
    def positives(self) -> int:
        return sum(self.labels)

    @property
    def base_rate(self) -> float | None:
        return (self.positives / len(self)) if self else None

    @property
    def cutoffs(self) -> tuple[str, ...]:
        return tuple(utc_isoformat(fold.cutoff_at) for fold in self.folds)

    def split_at_fold(self, index: int) -> tuple[CalibrationSample, CalibrationSample]:
        """Split temporally: folds ``[0, index)`` against folds ``[index, end)``.

        The only split offered, on purpose. Fitting on a random subset and
        validating on the rest would report a coverage guarantee that the
        temporal structure does not support.
        """
        if not 0 < index < len(self.folds):
            raise ValueError(
                f"fold index {index} must lie strictly inside 0..{len(self.folds)} "
                "so that both sides of the split are non-empty"
            )
        boundary = self.folds[index].start
        return (
            self._slice(self.folds[:index], 0, boundary),
            self._slice(self.folds[index:], boundary, len(self)),
        )

    def _slice(self, folds: Sequence[FoldSlice], start: int, stop: int) -> CalibrationSample:
        rebased = tuple(
            FoldSlice(cutoff_at=fold.cutoff_at, start=fold.start - start, stop=fold.stop - start)
            for fold in folds
        )
        return CalibrationSample(
            probabilities=self.probabilities[start:stop],
            labels=self.labels[start:stop],
            folds=rebased,
            experiment=self.experiment,
            code_hash=self.code_hash,
        )

    def fingerprint(self) -> str:
        """Content hash of the sample, independent of machine and file layout."""
        return hash_object(
            [
                {
                    "cutoff_at": utc_isoformat(fold.cutoff_at),
                    "rows": [
                        [self.probabilities[i], self.labels[i]]
                        for i in range(fold.start, fold.stop)
                    ],
                }
                for fold in self.folds
            ]
        )


def load_calibration_sample(experiment: Path | str) -> CalibrationSample:
    """Run the experiment's two passes and return its pooled sample.

    Requires the evidence ledger to be populated already -- ``make demo`` or
    ``scripts/bootstrap_data.py`` does that. This function deliberately does
    not ingest: a loader that quietly acquired evidence would make the
    sample's provenance depend on when it was first called.
    """
    spec, settings = load_experiment(experiment)
    backtester = Backtester(settings)
    plans = backtester.forecasting_pass(spec)
    scoring = backtester.scoring_pass(spec, plans)

    probabilities: list[float] = []
    labels: list[int] = []
    folds: list[FoldSlice] = []
    cursor = 0
    for fold in scoring.folds:
        if not fold.scoreable:
            continue
        stop = cursor + fold.forecasts
        # Canonical order within the fold. The scoring pass emits rows sorted by
        # forecast identifier, which is path-dependent; the multiset is not.
        rows = sorted(
            zip(scoring.probabilities[cursor:stop], scoring.labels[cursor:stop], strict=True)
        )
        probabilities.extend(row[0] for row in rows)
        labels.extend(row[1] for row in rows)
        folds.append(FoldSlice(cutoff_at=fold.cutoff_at, start=cursor, stop=stop))
        cursor = stop

    sample = CalibrationSample(
        probabilities=tuple(probabilities),
        labels=tuple(labels),
        folds=tuple(folds),
        experiment=spec.name,
        code_hash=code_hash(),
    )
    log.info(
        "fixture.calibration_loaded",
        experiment=spec.name,
        rows=len(sample),
        positives=sample.positives,
        folds=len(sample.folds),
        fingerprint=sample.fingerprint(),
    )
    return sample


@dataclass(frozen=True)
class FixtureManifest:
    """The pinned identity of a regenerated fixture."""

    manifest_version: int
    experiment: str
    rows: int
    positives: int
    folds: int
    cutoffs: tuple[str, ...]
    sample_fingerprint: str
    #: Informational: which source tree produced the pin. Not verified.
    code_hash: str
    caveat: str = SYNTHETIC_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "experiment": self.experiment,
            "rows": self.rows,
            "positives": self.positives,
            "folds": self.folds,
            "cutoffs": list(self.cutoffs),
            "sample_fingerprint": self.sample_fingerprint,
            "code_hash_when_pinned": self.code_hash,
            "caveat": self.caveat,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FixtureManifest:
        return cls(
            manifest_version=int(payload["manifest_version"]),
            experiment=str(payload["experiment"]),
            rows=int(payload["rows"]),
            positives=int(payload["positives"]),
            folds=int(payload["folds"]),
            cutoffs=tuple(payload["cutoffs"]),
            sample_fingerprint=str(payload["sample_fingerprint"]),
            code_hash=str(payload["code_hash_when_pinned"]),
            caveat=str(payload.get("caveat", SYNTHETIC_CAVEAT)),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(self.to_dict()) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> FixtureManifest:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def build_manifest(sample: CalibrationSample) -> FixtureManifest:
    """Derive the manifest a regenerated fixture must reproduce."""
    return FixtureManifest(
        manifest_version=MANIFEST_VERSION,
        experiment=sample.experiment,
        rows=len(sample),
        positives=sample.positives,
        folds=len(sample.folds),
        cutoffs=sample.cutoffs,
        sample_fingerprint=sample.fingerprint(),
        code_hash=sample.code_hash,
    )


def verify_manifest(sample: CalibrationSample, pinned: FixtureManifest) -> None:
    """Raise :class:`FixtureDriftError` unless ``sample`` reproduces ``pinned``.

    Only the sample's content is verified. ``code_hash`` is reported when it
    has moved, because that is the usual explanation for an intended change,
    but it is not itself a reason to fail.
    """
    current = build_manifest(sample)
    differences = [
        f"  {field}: pinned {getattr(pinned, field)!r} -> got {getattr(current, field)!r}"
        for field in _VERIFIED_FIELDS
        if getattr(current, field) != getattr(pinned, field)
    ]
    if not differences:
        return

    hint = (
        "The source tree has also changed since the pin, so this may be an "
        "intended update; re-pin with "
        "`python scripts/build_calibration_fixture.py --write`."
        if current.code_hash != pinned.code_hash
        else "The source tree is unchanged since the pin, so the generator is "
        "NOT deterministic and every number derived from it is unreproducible."
    )
    raise FixtureDriftError(
        "the regenerated fixture does not match its pinned manifest:\n"
        + "\n".join(differences)
        + f"\n{hint}"
    )
