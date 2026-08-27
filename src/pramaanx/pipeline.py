"""One cutoff, end to end.

Discovery -> union -> probability -> status. The M0 pipeline stops well short
of the full decomposition: there is no adjudicator between discovery and
probability, and no fitted calibrator or risk controller between probability
and status. Those stages are named explicitly below rather than hidden, so that
a report can never imply a guarantee the code does not provide.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pramaanx.calibration.base import (
    IDENTITY_CALIBRATION,
    PLACEHOLDER_POLICY,
    Calibrator,
    FixedThresholdController,
    IdentityCalibrator,
    RiskController,
)
from pramaanx.clock import Clock, SystemClock
from pramaanx.config import AlertPolicyConfig, Settings
from pramaanx.generators.base import (
    BaseGenerator,
    CandidateProposal,
    ForecastContext,
    get_generator_class,
)
from pramaanx.generators.base_rate import epistemic_uncertainty
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.event import EventHypothesis
from pramaanx.schemas.forecast import ForecastRecord, ForecastStatus
from pramaanx.timeguard.snapshots import Snapshot

log = get_logger(__name__)

#: Re-exported from :mod:`pramaanx.calibration.base`, which owns them now.
#: They were duplicated string literals while the pipeline was the only thing
#: that recorded them; once a fitted calibrator can be injected, two copies is
#: one copy too many -- a forecast whose label disagrees with the calibrator
#: that produced it is worse than one with no label.
__all__ = ["IDENTITY_CALIBRATION", "PLACEHOLDER_POLICY", "run_cutoff"]


def allocate_budget(settings: Settings) -> dict[str, int]:
    """Split the proposal budget across enabled generators.

    Shares are renormalised over the generators actually enabled, so removing a
    branch for an ablation does not silently shrink the total budget and make
    the ablation measure two things at once.
    """
    enabled = list(settings.generators.enabled)
    if not enabled:
        raise ValueError("no candidate generators are enabled")
    shares = {name: max(settings.generators.budget_shares.get(name, 0.0), 0.0) for name in enabled}
    total = sum(shares.values())
    if total <= 0.0:
        shares = dict.fromkeys(enabled, 1.0)
        total = float(len(enabled))
    budget = settings.generators.proposal_budget
    allocation = {name: max(1, int(budget * share / total)) for name, share in shares.items()}
    return dict(sorted(allocation.items()))


def build_generators(
    settings: Settings, ledger: EvidenceLedger, snapshot: Snapshot
) -> list[BaseGenerator]:
    generators: list[BaseGenerator] = []
    for name in settings.generators.enabled:
        cls = get_generator_class(name)
        factory = getattr(cls, "from_snapshot", None)
        if factory is None:
            raise TypeError(f"generator {name!r} does not implement from_snapshot()")
        generators.append(factory(ledger, settings, snapshot))
    return generators


def merge_proposals(proposals: Sequence[CandidateProposal]) -> list[CandidateProposal]:
    """Union equivalent candidates without erasing who proposed them.

    Merging is allowed; forgetting is not. The merged hypothesis carries the
    union of ``generated_by``, and each branch's trace is preserved under its
    own name so a later ablation can still attribute the candidate.
    """
    merged: dict[str, CandidateProposal] = {}
    for proposal in sorted(
        proposals, key=lambda item: (item.hypothesis.event_id, item.generator_name)
    ):
        key = proposal.candidate_key
        existing = merged.get(key)
        if existing is None:
            merged[key] = proposal.model_copy(
                update={"trace": {proposal.generator_name: proposal.trace}}
            )
            continue
        hypothesis: EventHypothesis = existing.hypothesis.model_copy(
            update={
                "generated_by": existing.hypothesis.generated_by | proposal.hypothesis.generated_by,
                "evidence": existing.hypothesis.evidence or proposal.hypothesis.evidence,
            }
        )
        merged[key] = existing.model_copy(
            update={
                "hypothesis": hypothesis,
                "generator_score": max(existing.generator_score, proposal.generator_score),
                "generator_name": "|".join(sorted(hypothesis.generated_by)),
                "trace": {**existing.trace, proposal.generator_name: proposal.trace},
            }
        )
    return sorted(
        merged.values(), key=lambda item: (-item.generator_score, item.hypothesis.event_id)
    )


def assign_status(
    probability: float,
    *,
    uncertainty: float,
    evidence_count: int,
    novelty: float,
    policy: AlertPolicyConfig,
) -> ForecastStatus:
    """Placeholder status assignment.

    Phase 8 replaces this entirely with a recall-first conformal controller
    whose thresholds are fitted on calibration data and locked before test
    evaluation. What survives from this function is only the ordering
    principle: uncertain cases are retained as MONITOR, ABSTAIN or
    INSUFFICIENT_EVIDENCE, never silently deleted.

    The miss-versus-false-alert trade-off encoded in the thresholds is a human
    decision. These constants are defaults for a demo, not a policy.
    """
    if evidence_count < policy.min_evidence_items and probability >= policy.monitor_threshold:
        return ForecastStatus.INSUFFICIENT_EVIDENCE
    if uncertainty >= 0.5 and probability >= policy.watch_threshold:
        # The interval is wider than the decision it would drive.
        return ForecastStatus.ABSTAIN
    if novelty >= policy.novelty_monitor_threshold:
        # A stream with no history cannot inherit a threshold that was chosen
        # on streams that have one. Retain it, do not promote it.
        return ForecastStatus.MONITOR
    if probability >= policy.alert_threshold:
        return ForecastStatus.ALERT
    if probability >= policy.watch_threshold:
        return ForecastStatus.WATCH
    # Everything below the watch threshold is retained as MONITOR. Nothing is
    # ever dropped, which is what protects recall at this stage.
    return ForecastStatus.MONITOR


@dataclass(frozen=True)
class CutoffRun:
    snapshot: Snapshot
    proposals: tuple[CandidateProposal, ...]
    forecasts: tuple[ForecastRecord, ...]

    @property
    def cutoff_at(self) -> str:
        return self.snapshot.cutoff_at.isoformat()


def run_cutoff(
    settings: Settings,
    ledger: EvidenceLedger,
    snapshot: Snapshot,
    *,
    clock: Clock | None = None,
    region_scope: list[str] | None = None,
    calibrator: Calibrator | None = None,
    controller: RiskController | None = None,
) -> CutoffRun:
    """Produce forecasts for one cutoff from one snapshot.

    ``calibrator`` and ``controller`` are injectable so that a fitted calibrator
    and a risk-controlled policy can replace the M0 defaults without touching
    this function. They default to :class:`IdentityCalibrator` and
    :class:`FixedThresholdController`, which reproduce M0's behaviour exactly --
    the identity mapping and the placeholder thresholds, extracted verbatim.

    The two are separate arguments because they fail differently. A
    miscalibrated probability is a modelling error a Brier score can measure; a
    badly chosen threshold is a *policy* error, a decision about how many misses
    are worth how many false alerts, which no amount of calibration data
    settles. Taking them together would hide the policy inside the model.
    """
    tick = clock or SystemClock()
    calibrator = calibrator or IdentityCalibrator()
    controller = controller or FixedThresholdController(settings.alerting)
    allocation = allocate_budget(settings)
    generators = build_generators(settings, ledger, snapshot)

    proposals: list[CandidateProposal] = []
    versions: dict[str, str] = {}
    for generator in generators:
        context = ForecastContext(
            cutoff_at=snapshot.cutoff_at,
            evidence_snapshot_id=snapshot.snapshot_id,
            proposal_budget=allocation[generator.name],
            region_scope=region_scope,
            horizon_days=settings.horizon_days,
        )
        produced = list(generator.propose(context))
        versions[generator.name] = generator.version
        proposals.extend(produced)

    merged = merge_proposals(proposals)
    merged = [
        item for item in merged if item.generator_score >= settings.generators.min_generator_score
    ][: settings.generators.proposal_budget]

    created_at = max(tick.now(), snapshot.cutoff_at)
    model_versions = {
        **versions,
        # Read off the injected objects rather than hard-coded, so a forecast
        # can never claim a calibration it was not produced under.
        "calibration": calibrator.version,
        "alert_policy": controller.version,
        "schema": str(snapshot.manifest.schema_version),
    }

    forecasts: list[ForecastRecord] = []
    for proposal in merged:
        uncertainty = epistemic_uncertainty(proposal)
        raw = proposal.generator_score
        probability = calibrator.apply(raw)
        forecasts.append(
            ForecastRecord(
                forecast_id=ForecastRecord.build_id(
                    snapshot.snapshot_hash, proposal.hypothesis.event_id
                ),
                cutoff_at=snapshot.cutoff_at,
                created_at=created_at,
                hypothesis=proposal.hypothesis,
                # The raw generator score is kept alongside the calibrated one.
                # A calibrator can be refitted later; the score it was applied
                # to cannot be recovered if it was overwritten.
                raw_probability=raw,
                calibrated_probability=probability,
                epistemic_uncertainty=uncertainty,
                status=controller.assign(
                    probability,
                    uncertainty=uncertainty,
                    evidence_count=len(proposal.hypothesis.evidence),
                    novelty=proposal.hypothesis.novelty_score,
                ),
                model_versions=dict(sorted(model_versions.items())),
                snapshot_hash=snapshot.snapshot_hash,
            )
        )

    log.info(
        "pipeline.cutoff_complete",
        cutoff=snapshot.cutoff_at.isoformat(),
        snapshot=snapshot.snapshot_id,
        proposals=len(proposals),
        forecasts=len(forecasts),
    )
    return CutoffRun(snapshot, tuple(merged), tuple(forecasts))
