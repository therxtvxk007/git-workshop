"""Hypothetical evidence in, a changed forecast out — without contaminating reality.

The feature the project exists to demonstrate, and the one with the sharpest
failure mode. A scenario asks "if this were also true, what would change?", and
the only way that question stays honest is if the hypothetical objects can never
reach a real snapshot. Two mechanisms enforce it, deliberately belt and braces:

*A separate namespace.* Every hypothetical cluster id is minted through
``stable_id(HYPOTHETICAL_PREFIX, ...)`` and therefore starts ``hyp_``. An id
that cannot be confused for a real one cannot be silently persisted as one.

*A copied world.* Interventions are applied to a copy of the cluster list. The
real ledger is opened read-only and never written during a scenario, so a
scenario run leaves the bronze it read byte-identical.

What comes back is a *sensitivity*, not a causal effect. If a forecast moves
when you assume an event, that tells you the model is sensitive to that
assumption — not that the assumption causes the outcome. The wording of
:data:`SCENARIO_CAVEAT` is load-bearing and should not be softened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pramaanx.adjudication import EvidenceWeightAdjudicator, adjudicate_all
from pramaanx.config import Settings
from pramaanx.generators.base import CandidateProposal
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.pipeline import run_cutoff
from pramaanx.timeguard.snapshots import SnapshotBuilder

log = get_logger(__name__)

SCENARIO_CAVEAT = (
    "Scenario sensitivity, not a causal effect. A forecast that moves under an "
    "assumption shows the model is sensitive to that assumption; it does not show "
    "the assumption causes the outcome. Hypothetical evidence is never written to "
    "the real ledger."
)


class ScenarioError(RuntimeError):
    """A scenario that cannot be run, with a reason the caller can act on."""


def _index(proposals: tuple[CandidateProposal, ...]) -> dict[str, CandidateProposal]:
    return {proposal.candidate_key: proposal for proposal in proposals}


def run_scenario(
    settings: Settings,
    *,
    cutoff_at: datetime,
    assumed_event_type: str,
    assumed_region: str,
    assumed_actor: str | None = None,
    assumed_support: int = 2,
    rationale: str = "operator hypothesis",
    limit: int = 25,
) -> dict[str, Any]:
    """Run a baseline and an intervened forecast, and diff them.

    The intervention is expressed as an assumed event the operator supplies. It
    is dated at the cutoff rather than after it: a scenario changes the past a
    forecast reasons *from*, never the future it reasons *about*. Assuming an
    event after the cutoff would be assuming the answer.
    """
    if assumed_support < 1:
        raise ScenarioError("assumed_support must be at least 1")

    ledger = EvidenceLedger(settings)
    snapshot = SnapshotBuilder(settings, ledger).build(cutoff_at, persist=False)
    if len(snapshot) == 0:
        raise ScenarioError(
            f"no evidence available at {cutoff_at.isoformat()}; a scenario needs a "
            "baseline to differ from"
        )

    baseline = run_cutoff(settings, ledger, snapshot)
    baseline_index = _index(baseline.proposals)

    # The intervention. Built as a proposal in the hypothetical namespace rather
    # than injected into bronze: nothing here touches stored evidence, and the
    # id it carries could not be mistaken for a real observation if it did.
    from pramaanx.hashing import stable_id
    from pramaanx.scenarios.interface import HYPOTHETICAL_PREFIX
    from pramaanx.schemas.event import EventHypothesis

    assumed_id = stable_id(
        HYPOTHETICAL_PREFIX, assumed_event_type, assumed_region, assumed_actor or "", rationale
    )
    assumed = CandidateProposal(
        hypothesis=EventHypothesis(
            event_id=assumed_id,
            event_type=assumed_event_type,
            actor_ids=[assumed_actor] if assumed_actor else [],
            location_cells={assumed_region: 1.0},
            time_bucket_probabilities={"0-7d": 1.0},
        ),
        generator_name="scenario",
        # An assumption is asserted, not inferred. Recording it at certainty is
        # honest about what the operator said; the caveat carries the rest.
        generator_score=0.99,
        trace={"assumed": True, "rationale": rationale, "support": assumed_support},
    )

    # A copy, so the baseline list the diff compares against is untouched.
    intervened = [*baseline.proposals, assumed]
    states, report = adjudicate_all(
        EvidenceWeightAdjudicator(), intervened, as_of=snapshot.cutoff_at
    )
    beliefs = {state.candidate_id: state for state in states}

    deltas: list[dict[str, Any]] = []
    for proposal in intervened:
        key = proposal.candidate_key
        belief = beliefs.get(key)
        before = baseline_index.get(key)
        deltas.append(
            {
                "event_id": key,
                "event_type": proposal.hypothesis.event_type,
                "regions": proposal.hypothesis.location_cells,
                "hypothetical": key.startswith(f"{HYPOTHETICAL_PREFIX}_"),
                "baseline_score": before.generator_score if before else None,
                "scenario_probability": belief.probability if belief else None,
                "verdict": belief.verdict.value if belief else None,
                "appeared": before is None,
            }
        )

    def _shift(entry: dict[str, Any]) -> float:
        before = entry["baseline_score"]
        after = entry["scenario_probability"]
        if not isinstance(before, float) or not isinstance(after, float):
            return 0.0
        return abs(after - before)

    moved = [entry for entry in deltas if _shift(entry) > 0.0]
    moved.sort(key=_shift, reverse=True)

    # The check that makes the whole feature trustworthy, run every time rather
    # than only in tests: the scenario must not have written anything.
    post = SnapshotBuilder(settings, ledger).build(cutoff_at, persist=False)
    if post.snapshot_hash != snapshot.snapshot_hash:
        raise ScenarioError(
            "the scenario changed the real snapshot; refusing to return a result. "
            f"{snapshot.snapshot_hash} -> {post.snapshot_hash}"
        )

    log.info("scenario.complete", assumed=assumed_id, candidates=len(deltas))
    return {
        "cutoff_at": snapshot.cutoff_at.isoformat(),
        "snapshot_hash": snapshot.snapshot_hash,
        "real_snapshot_unchanged": True,
        "assumption": {
            "event_id": assumed_id,
            "event_type": assumed_event_type,
            "region": assumed_region,
            "actor": assumed_actor,
            "rationale": rationale,
            "namespace": HYPOTHETICAL_PREFIX,
        },
        "adjudication": report.model_dump(mode="json"),
        "baseline_candidates": len(baseline.proposals),
        "scenario_candidates": len(intervened),
        "most_moved": moved[:limit],
        "caveat": SCENARIO_CAVEAT,
    }
