"""One composed offline run, from generated evidence to a scored forecast.

This is the plan's first deliverable (S41): a reproducible engineering run, on
synthetic data, that exercises every join between the pieces. Integration
errors -- a calendar mismatch, a role that leaks, a forecast scored against a
snapshot it could see -- do not show up in unit tests. They show up here.

The order matters and is the point:

1. evidence is committed to the as-of store, with reporting delay;
2. the panel is built from the roster and labelled *as of each origin*, so a
   late report is missing at the early origin and present later;
3. roles are assigned before any model runs;
4. each model is fitted and predicted inside a runtime attempt;
5. the forecast is frozen to disk **before** the matured reference is read;
6. scoring reads the frozen file, never a regenerated prediction.

Step 5 is the one that is easy to skip and impossible to recover from. A
scorer that re-runs ``predict`` is scoring today's model against yesterday's
outcome, and no amount of care elsewhere repairs that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from pramaanx.clock import Clock, FixedClock
from pramaanx.core.asof import RevisionStore
from pramaanx.core.contexts import (
    FitContext,
    ForecastContext,
    InformationProfile,
    OriginRole,
    ScoreContext,
)
from pramaanx.core.errors import CapabilityUnsupportedError, ContractViolationError
from pramaanx.core.rng import RandomStreams
from pramaanx.geo.roster import Roster, roster_from_districts
from pramaanx.hashing import canonical_json, hash_object, utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.models.base import ForecastArtifact
from pramaanx.models.ladder import LADDER
from pramaanx.panel.grid import PanelSpec, build_panel
from pramaanx.panel.outcomes import (
    ObservationStatus,
    attach_outcomes,
    count_in_window,
    coverage_report,
    scorable,
    trainable,
)
from pramaanx.panel.windows import Window, monthly_origins
from pramaanx.protocol.splitter import SplitManifest, check_purge, chronological_split
from pramaanx.runtime.runner import RunManager
from pramaanx.simlab.generators import (
    INCIDENT_TABLE,
    WorldSpec,
    generate,
    labels_from_records,
    to_revisions,
)
from pramaanx.verify.lints import run_all
from pramaanx.verify.scores import ScoreResult, brier, log_loss, skill

log = get_logger(__name__)

FORECASTS_DIR = "forecasts"


@dataclass(frozen=True)
class OfflineSpec:
    """Everything the run needs. No defaults that decide anything scientific."""

    world: WorldSpec
    window_days: int = 30
    maturation_days: int = 14
    seed: int = 0
    n_origins: int = 18
    #: Districts whose coverage is deliberately withheld, to prove that an
    #: outage produces unknown labels rather than zeros.
    unavailable_districts: tuple[str, ...] = ()
    models: tuple[type, ...] = LADDER

    def roster(self) -> Roster:
        return Roster(
            versions=(
                roster_from_districts("offline-v1", self.world.start, list(self.world.districts)),
            )
        )


@dataclass
class OfflineReport:
    """What one run produced, in a shape a manifest can hold."""

    run_id: str
    input_manifest: str
    reference_manifest: str
    split_identity: str
    issue_origin: datetime
    panel_rows: int
    coverage: dict[str, int]
    forecasts: dict[str, str] = field(default_factory=dict)
    #: Models that could not produce a forecast, and why. Recorded rather than
    #: allowed to abort the run: a model that declines difficult rows must not
    #: also remove them from every other model's denominator (S33.3).
    failures: dict[str, str] = field(default_factory=dict)
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_gaps: dict[str, dict[str, str]] = field(default_factory=dict)
    lints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "input_manifest": self.input_manifest,
            "reference_manifest": self.reference_manifest,
            "split_identity": self.split_identity,
            "issue_origin": utc_isoformat(self.issue_origin),
            "panel_rows": self.panel_rows,
            "coverage": dict(sorted(self.coverage.items())),
            "forecasts": dict(sorted(self.forecasts.items())),
            "failures": dict(sorted(self.failures.items())),
            "scores": {key: self.scores[key] for key in sorted(self.scores)},
            "capability_gaps": {
                key: self.capability_gaps[key] for key in sorted(self.capability_gaps)
            },
            "lints": self.lints,
        }

    def identity(self) -> str:
        """Everything except the run id, which differs between two runs of the
        same protocol and must not make their reports look different."""
        payload = self.to_dict()
        payload.pop("run_id")
        return hash_object(payload)


def _label_panel(
    store: RevisionStore,
    panel: pl.DataFrame,
    *,
    spec: OfflineSpec,
    manifest: str,
    origins: tuple[datetime, ...],
    as_of: datetime,
) -> pl.DataFrame:
    """Label each origin's rows using only what the store had at that cutoff.

    The cutoff used here is the *end* of the outcome window plus maturation --
    the point at which the label is allowed to be read -- not the origin. Using
    the origin would label a window before it happened; using "now" would let a
    late report retroactively change an early label.
    """
    coverage = {
        district: (
            ObservationStatus.UNAVAILABLE
            if district in spec.unavailable_districts
            else ObservationStatus.OBSERVED
        )
        for district, _state in spec.world.districts
    }

    frames: list[pl.DataFrame] = []
    for origin in origins:
        rows = panel.filter(pl.col("origin") == origin)
        window_start = rows["window_start"][0]
        window_end = rows["window_end"][0]
        settle = window_end + timedelta(days=spec.maturation_days)

        label_ctx = ForecastContext(
            issue_time=settle,
            cutoff_at=settle,
            input_manifest=manifest,
            profile=InformationProfile.PROSPECTIVE_OBSERVED,
            role=OriginRole.TRAIN,
            policy_hash="offline-policy",
            boundary_version="offline-v1",
        )
        records = store.read(INCIDENT_TABLE, ctx=label_ctx).payloads().to_dicts()
        labels, instants = labels_from_records(records)
        counts, _ = count_in_window(
            labels, window=Window(window_start, window_end), instants=instants
        )
        frames.append(
            attach_outcomes(
                rows,
                counts=counts,
                coverage=coverage,
                maturation_days=spec.maturation_days,
                as_of=as_of,
                label_manifest=manifest,
                label_available_time=settle,
            )
        )
    return pl.concat(frames)


def _freeze(root: Path, run_id: str, model_id: str, frame: pl.DataFrame) -> tuple[Path, str]:
    """Write the forecast before any outcome is read, and hash what was written."""
    directory = root / FORECASTS_DIR / run_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{model_id}.json"
    payload = canonical_json(frame.sort(["district_id", "family"]).to_dicts())
    target.write_text(payload, encoding="utf-8")
    return target, hash_object(payload)


def _score_frozen(
    frozen: Path, reference: pl.DataFrame
) -> tuple[ScoreResult, ScoreResult, list[float], list[int]]:
    """Score a file, not a model. The distinction is the protocol (S29.3)."""
    forecasts = pl.read_json(frozen)
    joined = forecasts.join(
        reference.select(["district_id", "family", "y_observed"]),
        on=["district_id", "family"],
        how="inner",
    ).sort(["district_id", "family"])
    probabilities = [float(value) for value in joined["p_occ"].to_list()]
    outcomes = [1 if int(value) > 0 else 0 for value in joined["y_observed"].to_list()]
    return (
        brier(probabilities, outcomes),
        log_loss(probabilities, outcomes),
        probabilities,
        outcomes,
    )


def run_offline(root: Path, spec: OfflineSpec, *, clock: Clock | None = None) -> OfflineReport:
    """Run the whole thing once. Deterministic given ``spec.seed``."""
    root = Path(root)
    rng = RandomStreams(root_seed=spec.seed)
    world_end = spec.world.calendar.instant(
        spec.world.start + timedelta(days=spec.world.days + 400)
    )
    the_clock = clock or FixedClock(world_end)
    store = RevisionStore(root / "store", clock=the_clock)
    manager = RunManager(root / "runs", clock=the_clock)
    run_id = f"offline-{spec.seed}"

    # 1. Evidence into the store.
    incidents = generate(spec.world, rng=rng)
    receipt = store.commit(
        to_revisions(incidents, spec=spec.world, ingested_at=world_end),
        idempotency_key=f"{run_id}:world",
    )

    # 2. Panel and labels, each origin as of its own settle time.
    roster = spec.roster()
    origins = monthly_origins(
        spec.world.start,
        spec.world.start + timedelta(days=31 * spec.n_origins),
        calendar=spec.world.calendar,
    )[: spec.n_origins]
    if len(origins) < 4:
        raise ContractViolationError("an offline run needs at least four origins")

    panel_spec = PanelSpec(
        origins=origins,
        roster=roster,
        calendar=spec.world.calendar,
        window_days=spec.window_days,
    )
    panel = build_panel(panel_spec)
    labelled = _label_panel(
        store,
        panel,
        spec=spec,
        manifest=receipt.manifest_hash,
        origins=origins,
        as_of=world_end,
    )

    # 3. Roles, before a model exists.
    split = _split_for(origins, spec)
    issue_origin = split.origins_with(OriginRole.RETRO_TEST)[0]
    check_purge(split, issue_time=issue_origin)

    training = trainable(
        labelled.filter(pl.col("origin").is_in(list(split.training_origins_for(issue_origin)))),
        fit_cutoff=issue_origin,
    )
    issue_rows = panel.filter(pl.col("origin") == issue_origin)
    window_start = issue_rows["window_start"][0]
    window_end = issue_rows["window_end"][0]

    fit_ctx = FitContext(
        issue_time=issue_origin,
        cutoff_at=issue_origin,
        input_manifest=receipt.manifest_hash,
        profile=InformationProfile.PROSPECTIVE_OBSERVED,
        role=OriginRole.RETRO_TEST,
        policy_hash="offline-policy",
        boundary_version="offline-v1",
        fit_cutoff=issue_origin,
        label_manifest=receipt.manifest_hash,
        maturation_days=spec.maturation_days,
        training_origins=split.training_origins_for(issue_origin),
    )
    forecast_ctx = fit_ctx.forecast_context()

    report = OfflineReport(
        run_id=run_id,
        input_manifest=receipt.manifest_hash,
        reference_manifest=receipt.manifest_hash,
        split_identity=split.identity(),
        issue_origin=issue_origin,
        panel_rows=panel.height,
        coverage=coverage_report(labelled),
    )

    # 4-5. Fit, predict, freeze -- all before any outcome is read.
    for factory in spec.models:
        model = factory()
        try:
            with manager.attempt(
                run_id=run_id,
                stage=f"forecast:{model.model_id}",
                config={"seed": spec.seed, "window_days": spec.window_days},
                rng=rng.describe(),
            ) as attempt:
                attempt.record_context(forecast_ctx.identity())
                attempt.record_input(receipt.manifest_hash)
                fitted = model.fit(training, ctx=fit_ctx, rng=rng)
                forecast = model.predict(issue_rows, model=fitted, ctx=forecast_ctx, rng=rng)
                rows = forecast.summarise(window_start, window_end)
                frozen, digest = _freeze(
                    root, run_id, model.model_id, forecast.to_frame(window_start, window_end)
                )
                attempt.record_output(digest)

                report.forecasts[model.model_id] = digest
                report.capability_gaps[model.model_id] = dict(
                    sorted(forecast.capabilities.unresolved.items())
                )
                report.lints[model.model_id] = run_all(
                    rows, capabilities=forecast.capabilities
                ).to_dict()
                for gap in _horizon_gaps(forecast, window_start, window_end):
                    attempt.warn(gap)
        except (CapabilityUnsupportedError, ContractViolationError) as error:
            # A model that refuses a cell it cannot honestly forecast is
            # behaving correctly -- hist12 does exactly this for a district
            # whose coverage failed. Aborting the run would let one model's
            # refusal decide which rows every other model is scored on, so the
            # refusal is recorded and the run continues. The attempt row is
            # already FAILED, written by the runtime before the raise.
            report.failures[model.model_id] = error.message
            log.warning("offline.model_declined", model=model.model_id, reason=error.message)
            continue
        log.info("offline.frozen", model=model.model_id, path=frozen.as_posix())

    # 6. Only now is the reference read, and only from the frozen files.
    score_ctx = ScoreContext(
        issue_time=world_end,
        cutoff_at=world_end,
        input_manifest=receipt.manifest_hash,
        profile=InformationProfile.PROSPECTIVE_OBSERVED,
        role=OriginRole.RETRO_TEST,
        policy_hash="offline-policy",
        boundary_version="offline-v1",
        forecast_artifact=hash_object(sorted(report.forecasts.items())),
        reference_manifest=receipt.manifest_hash,
        maturation_days=spec.maturation_days,
        evaluation_contract=hash_object({"metrics": ["brier", "log_loss"]}),
    )
    reference = scorable(labelled.filter(pl.col("origin") == issue_origin))

    baseline: ScoreResult | None = None
    for model_id in sorted(report.forecasts):
        frozen = root / FORECASTS_DIR / run_id / f"{model_id}.json"
        brier_result, log_result, _, _ = _score_frozen(frozen, reference)
        if model_id == "ladder.climatology":
            baseline = brier_result
        report.scores[model_id] = {
            "brier": brier_result.to_dict(),
            "log_loss": log_result.to_dict(),
            "score_context": score_ctx.identity(),
        }

    if baseline is not None:
        for model_id in sorted(report.forecasts):
            frozen = root / FORECASTS_DIR / run_id / f"{model_id}.json"
            model_brier, _, _, _ = _score_frozen(frozen, reference)
            report.scores[model_id]["brier_skill_vs_climatology"] = skill(
                model_brier, baseline
            ).to_dict()

    (root / "run_manifest.json").write_text(canonical_json(report.to_dict()), encoding="utf-8")
    return report


def _split_for(origins: tuple[datetime, ...], spec: OfflineSpec) -> SplitManifest:
    """Bands by position, so a short synthetic run still exercises every role."""
    count = len(origins)
    return chronological_split(
        origins,
        select_from=origins[int(count * 0.5)],
        calibrate_from=origins[int(count * 0.65)],
        retro_test_from=origins[int(count * 0.8)],
        prospective_from=origins[-1],
        window_days=spec.window_days,
        maturation_days=spec.maturation_days,
        boundary_versions=("offline-v1",),
        calendar=spec.world.calendar.identity(),
    )


def _horizon_gaps(forecast: ForecastArtifact, start: datetime, end: datetime) -> list[str]:
    """Record, per model, which horizons it cannot answer and why.

    A window-only model declining a 7-day horizon is a finding about the
    model, and the run manifest is where a reader should be able to see it
    rather than infer it from a blank cell.
    """
    midpoint = start + (end - start) / 2
    try:
        forecast.window(start, midpoint)
    except (CapabilityUnsupportedError, ContractViolationError) as error:
        return [f"shorter horizon unavailable: {error.message}"]
    return []
