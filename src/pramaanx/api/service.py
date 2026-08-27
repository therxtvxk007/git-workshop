"""Read models and the query layer the API serves.

Kept separate from the HTTP layer so the same functions back the dashboard, the
CLI and any future client. The rule this module enforces is that nothing leaves
the system without the four things that make a forecast interpretable: the
cutoff it was made at, the snapshot it saw, the calibration it was produced
under, and what would have contradicted it.

A probability without those is a number, and a number is what gets quoted
without its caveats.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pramaanx.adjudication import BeliefState, EvidenceWeightAdjudicator, adjudicate_all
from pramaanx.config import Settings
from pramaanx.ingest.contracts import SOURCE_CONTRACTS, unverified
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.pipeline import run_cutoff
from pramaanx.schemas.forecast import ForecastRecord
from pramaanx.timeguard.snapshots import SnapshotBuilder

log = get_logger(__name__)

#: Repeated on every forecast the API returns. The system forecasts
#: distributions over event type, region and window; it does not predict a
#: specific attack, and an interface that lets a reader forget that is unsafe
#: whatever its numbers say.
INTERPRETATION = (
    "A probability for an event TYPE in a REGION over a TIME WINDOW. Not a "
    "prediction of a specific incident, target, date or perpetrator. Uncalibrated "
    "unless model_versions says otherwise."
)


class ServiceError(RuntimeError):
    """A request that cannot be served, with a reason a caller can act on."""


class ForecastService:
    """Everything the API and dashboard read, in one place."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ledger = EvidenceLedger(settings)
        self.snapshots = SnapshotBuilder(settings, self.ledger)

    # ---- health and provenance -------------------------------------------

    def health(self) -> dict[str, Any]:
        """Liveness plus the two things that make a green tick meaningful."""
        try:
            observations = len(self.ledger.read_observations())
        except Exception as exc:  # pragma: no cover - only on a broken ledger
            return {"status": "degraded", "reason": str(exc), "observations": 0}
        manifests = self.snapshots.list_snapshots()
        return {
            "status": "ok",
            "observations": observations,
            "snapshots": len(manifests),
            # A source nobody has ever verified is a health fact, not a
            # footnote: evidence from it is in every forecast downstream.
            "unverified_sources": [contract.source_id for contract in unverified()],
        }

    def sources(self) -> list[dict[str, Any]]:
        """Every source, and whether its contract has ever been answered."""
        return [
            {
                "source_id": contract.source_id,
                "state": contract.state.value,
                "contract_version": contract.contract_version,
                "live_verified_on": (
                    contract.live_verified_on.isoformat() if contract.live_verified_on else None
                ),
                "live_verification_scope": contract.live_verification_scope,
                "blocker": contract.blocker,
            }
            for contract in sorted(SOURCE_CONTRACTS.values(), key=lambda c: c.source_id)
        ]

    def snapshot_list(self) -> list[dict[str, Any]]:
        entries = []
        for manifest in self.snapshots.list_snapshots():
            entries.append(
                {
                    "snapshot_id": manifest.snapshot_id,
                    "cutoff_at": manifest.cutoff_at.isoformat(),
                    "observations": manifest.observation_count,
                    "sources": manifest.source_counts,
                    "source_contracts": manifest.source_contracts,
                    "snapshot_hash": manifest.snapshot_hash,
                }
            )
        return sorted(entries, key=lambda item: item["cutoff_at"], reverse=True)

    # ---- forecasting -----------------------------------------------------

    def forecast(
        self,
        cutoff_at: datetime,
        *,
        region_scope: list[str] | None = None,
        limit: int = 50,
        adjudicate: bool = True,
    ) -> dict[str, Any]:
        """Forecasts at a cutoff, with evidence and belief states attached."""
        snapshot = SnapshotBuilder(self.settings, self.ledger).build(cutoff_at, persist=False)
        if len(snapshot) == 0:
            raise ServiceError(
                f"no evidence was available at {cutoff_at.isoformat()}. This is a real "
                "state, not an error: ingest a window that ends at or before the cutoff."
            )
        run = run_cutoff(self.settings, self.ledger, snapshot, region_scope=region_scope)

        beliefs: dict[str, BeliefState] = {}
        adjudication: dict[str, Any] | None = None
        if adjudicate and run.proposals:
            states, report = adjudicate_all(
                EvidenceWeightAdjudicator(), run.proposals, as_of=snapshot.cutoff_at
            )
            beliefs = {state.candidate_id: state for state in states}
            adjudication = report.model_dump(mode="json")

        ranked = sorted(run.forecasts, key=lambda f: f.calibrated_probability, reverse=True)
        return {
            "cutoff_at": snapshot.cutoff_at.isoformat(),
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "observations": len(snapshot),
            "source_contracts": snapshot.manifest.source_contracts,
            "forecast_count": len(run.forecasts),
            "adjudication": adjudication,
            "interpretation": INTERPRETATION,
            "forecasts": [
                self._render(forecast, beliefs.get(forecast.hypothesis.event_id))
                for forecast in ranked[:limit]
            ],
        }

    def _render(self, forecast: ForecastRecord, belief: BeliefState | None) -> dict[str, Any]:
        """One forecast, with everything needed to argue with it."""
        hypothesis = forecast.hypothesis
        supporting = [ref for ref in hypothesis.evidence if ref.stance == "supports"]
        contradicting = [ref for ref in hypothesis.evidence if ref.stance == "contradicts"]
        return {
            "forecast_id": forecast.forecast_id,
            "event_id": hypothesis.event_id,
            "event_type": hypothesis.event_type,
            "regions": hypothesis.location_cells,
            "time_buckets": hypothesis.time_bucket_probabilities,
            "actors": hypothesis.actor_ids,
            "raw_probability": forecast.raw_probability,
            "calibrated_probability": forecast.calibrated_probability,
            "epistemic_uncertainty": forecast.epistemic_uncertainty,
            "status": forecast.status.value,
            "novelty": hypothesis.novelty_score,
            "model_versions": forecast.model_versions,
            "snapshot_hash": forecast.snapshot_hash,
            "evidence": {
                "supporting": len(supporting),
                "contradicting": len(contradicting),
                # The count that matters. Ten outlets rewriting one wire story
                # are one piece of evidence, and a reader who cannot see that
                # cannot judge the forecast.
                "independent_clusters": len({ref.cluster_key for ref in hypothesis.evidence}),
                "items": [
                    {
                        "claim": ref.claim,
                        "stance": ref.stance,
                        "cluster": ref.cluster_key,
                        "reliability": ref.reliability,
                    }
                    for ref in hypothesis.evidence[:10]
                ],
            },
            "belief": self._render_belief(belief),
        }

    @staticmethod
    def _render_belief(belief: BeliefState | None) -> dict[str, Any] | None:
        if belief is None:
            return None
        return {
            "verdict": belief.verdict.value,
            "probability": belief.probability,
            "prior": belief.prior,
            "independent_support": belief.independent_support,
            "independent_contradiction": belief.independent_contradiction,
            "repeated_items": belief.repeated_items,
            "unresolved_fields": list(belief.unresolved_fields),
            "trial_disagreement": belief.trial_disagreement,
            "adjudicator_version": belief.adjudicator_version,
            # The reason anyone should trust the number: every step that moved
            # it, in order, replayable back to the prior.
            "audit_trail": belief.audit_trail,
        }

    # ---- evidence --------------------------------------------------------

    def evidence(self, observation_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Provenance for specific observations.

        Payload bytes are deliberately not returned. Several sources here are
        licensed for analysis and not redistribution, and an API that hands back
        raw licensed text is a licence breach wearing a JSON content type.
        """
        wanted = set(observation_ids)
        return [
            {
                "observation_id": item.observation_id,
                "source_id": item.source_id,
                "first_observed_at": item.first_observed_at.isoformat(),
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "uri": str(item.uri) if item.uri else None,
                "licence": item.licence,
                "raw_content_hash": item.raw_content_hash,
                "redistributable": False,
            }
            for item in self.ledger.read_observations()
            if item.observation_id in wanted
        ]
