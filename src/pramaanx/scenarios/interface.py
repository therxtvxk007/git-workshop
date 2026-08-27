"""The hypothetical-scenario interface.

"What if the ceasefire collapses in March?" is a different question from "what
will happen in March?", and a system that answers the second cannot answer the
first by having its inputs quietly edited. Two things have to be true for a
scenario answer to be worth anything:

*The assumption must be visible in the output.* Every artefact a scenario
produces is marked hypothetical, from the cluster up. An assumed event that
reaches persistence unmarked is indistinguishable from a fabricated
observation, and six months later nobody can tell which forecasts were
conditional.

*The scenario must not touch the real world.* Interventions produce a new
cluster set and a new graph. The ledger, the snapshot and the baseline clusters
are never mutated -- :func:`apply_scenario` takes copies and returns new
objects, so a scenario run cannot leave a trace in the evidence that produced
it.

What a scenario is *not* is a causal model. Injecting a ceasefire collapse and
watching the forecasts move tells you what this pipeline's rules do with that
input. It does not tell you what the world would do, and
:attr:`ScenarioResult.interpretation` says so in words that are hard to quote
out of context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from pramaanx.entities.dedupe import EventCluster, IndependenceGroup
from pramaanx.entities.resolve import EntityIndex
from pramaanx.generators.base import CandidateProposal
from pramaanx.graph.evidence_graph import EvidenceGraph, build_graph
from pramaanx.hashing import stable_id
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

log = get_logger(__name__)

#: Prefix on every hypothetical cluster id. Distinct from the real ``clu_``
#: prefix so that a stray identifier is recognisable on sight, in a log line or
#: a database row, without needing the object it came from.
HYPOTHETICAL_PREFIX = "hyp"


class InterventionKind(StrEnum):
    ADD_EVENT = "add_event"
    REMOVE_EVENT = "remove_event"
    SHIFT_TIME = "shift_time"
    REPLACE_ACTOR = "replace_actor"


class Intervention(PramaanModel, ABC):
    """One edit to the evidence, applied to produce a counterfactual world."""

    kind: InterventionKind
    rationale: str = ""

    @abstractmethod
    def apply(self, clusters: Sequence[EventCluster], *, cutoff_at: datetime) -> list[EventCluster]:
        """Return a new cluster list. Must not mutate ``clusters``."""


class AddEvent(Intervention):
    """Assert an event that did not occur, or has not yet been reported."""

    kind: Literal[InterventionKind.ADD_EVENT] = InterventionKind.ADD_EVENT
    event_type: str
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_entity_id: str | None = None
    occurred_at: UtcDatetime
    #: How much independent support to pretend this event has. Capped, because
    #: a scenario that assumes overwhelming corroboration is assuming the
    #: conclusion rather than the event.
    assumed_support: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def _check_participants(self) -> AddEvent:
        if not self.actor_ids and not self.location_entity_id:
            raise ValueError("an assumed event needs at least an actor or a location")
        return self

    def apply(self, clusters: Sequence[EventCluster], *, cutoff_at: datetime) -> list[EventCluster]:
        if self.occurred_at > cutoff_at:
            raise ValueError(
                f"assumed event at {self.occurred_at.isoformat()} is after the scenario "
                f"cutoff {cutoff_at.isoformat()}; a scenario changes the past it "
                "reasons from, not the future it reasons about"
            )
        cluster_id = stable_id(
            HYPOTHETICAL_PREFIX,
            self.event_type,
            sorted(self.actor_ids),
            sorted(self.target_ids),
            self.location_entity_id or "",
            self.occurred_at.isoformat(),
        )
        assumed = EventCluster(
            cluster_id=cluster_id,
            event_type=self.event_type,
            actor_ids=sorted(set(self.actor_ids)),
            target_ids=sorted(set(self.target_ids)),
            location_entity_id=self.location_entity_id,
            window_start=self.occurred_at,
            window_end=self.occurred_at,
            first_observed_at=self.occurred_at,
            last_observed_at=self.occurred_at,
            mention_ids=[],
            # Synthetic independence groups carry the assumed support without
            # inventing mentions. An assumed event has no supporting_span, and
            # fabricating one would put text in the evidence pack that no
            # source ever wrote.
            independence_groups=[
                IndependenceGroup(
                    group_id=f"{cluster_id}_assumed_{position}",
                    mention_ids=[],
                    representative_span=f"[assumed by scenario] {self.rationale}"[:512],
                )
                for position in range(self.assumed_support)
            ],
            modality_counts={"asserted": self.assumed_support},
            undated_mention_ids=[],
            hypothetical=True,
        )
        return [*clusters, assumed]


class RemoveEvent(Intervention):
    """Suppress an event that did occur."""

    kind: Literal[InterventionKind.REMOVE_EVENT] = InterventionKind.REMOVE_EVENT
    cluster_ids: list[str] = Field(min_length=1)

    def apply(self, clusters: Sequence[EventCluster], *, cutoff_at: datetime) -> list[EventCluster]:
        del cutoff_at
        targets = set(self.cluster_ids)
        missing = sorted(targets - {cluster.cluster_id for cluster in clusters})
        if missing:
            # A scenario removing something that is not there is almost always a
            # stale identifier, and silently succeeding would produce a
            # "counterfactual" identical to the baseline.
            raise KeyError(f"cannot remove clusters that are not present: {missing}")
        return [cluster for cluster in clusters if cluster.cluster_id not in targets]


class ShiftTime(Intervention):
    """Move an event earlier or later."""

    kind: Literal[InterventionKind.SHIFT_TIME] = InterventionKind.SHIFT_TIME
    cluster_ids: list[str] = Field(min_length=1)
    delta_days: float

    def apply(self, clusters: Sequence[EventCluster], *, cutoff_at: datetime) -> list[EventCluster]:
        shift = timedelta(days=self.delta_days)
        targets = set(self.cluster_ids)
        shifted: list[EventCluster] = []
        for cluster in clusters:
            if cluster.cluster_id not in targets:
                shifted.append(cluster)
                continue
            new_start = cluster.window_start + shift
            new_observed = min(cluster.first_observed_at + shift, cutoff_at)
            if new_start > cutoff_at:
                raise ValueError(
                    f"shifting {cluster.cluster_id} by {self.delta_days} days moves it "
                    f"past the scenario cutoff"
                )
            shifted.append(
                cluster.model_copy(
                    update={
                        "cluster_id": stable_id(
                            HYPOTHETICAL_PREFIX, cluster.cluster_id, str(self.delta_days)
                        ),
                        "window_start": new_start,
                        "window_end": cluster.window_end + shift,
                        "first_observed_at": new_observed,
                        "last_observed_at": max(cluster.last_observed_at + shift, new_observed),
                        "hypothetical": True,
                    }
                )
            )
        return shifted


class ReplaceActor(Intervention):
    """Swap one actor for another wherever it appears.

    The counterfactual the evaluation harness names as entity replacement: if
    the same events had involved a different group, would the pipeline have
    reached the same conclusion? A model that answers identically regardless of
    the actor is keying on the calendar rather than on who is doing what.
    """

    kind: Literal[InterventionKind.REPLACE_ACTOR] = InterventionKind.REPLACE_ACTOR
    original_entity_id: str
    replacement_entity_id: str

    @model_validator(mode="after")
    def _check_distinct(self) -> ReplaceActor:
        if self.original_entity_id == self.replacement_entity_id:
            raise ValueError("replacement actor is identical to the original")
        return self

    def apply(self, clusters: Sequence[EventCluster], *, cutoff_at: datetime) -> list[EventCluster]:
        del cutoff_at
        swapped: list[EventCluster] = []
        for cluster in clusters:
            if (
                self.original_entity_id not in cluster.actor_ids
                and self.original_entity_id not in cluster.target_ids
            ):
                swapped.append(cluster)
                continue
            actors = sorted(
                {
                    self.replacement_entity_id if item == self.original_entity_id else item
                    for item in cluster.actor_ids
                }
            )
            targets = sorted(
                {
                    self.replacement_entity_id if item == self.original_entity_id else item
                    for item in cluster.target_ids
                }
            )
            swapped.append(
                cluster.model_copy(
                    update={
                        "cluster_id": stable_id(
                            HYPOTHETICAL_PREFIX, cluster.cluster_id, self.replacement_entity_id
                        ),
                        "actor_ids": actors,
                        "target_ids": targets,
                        "hypothetical": True,
                    }
                )
            )
        return swapped


class Scenario(VersionedModel):
    """A named set of interventions, with provenance."""

    scenario_id: str
    name: str
    description: str
    cutoff_at: UtcDatetime
    #: Who posed the question. Required, because a scenario is somebody's
    #: assumption and an unattributed assumption is soon read as a finding.
    author: str
    # Discriminated on ``kind`` rather than left to smart-union matching. Two
    # interventions here share a field shape (``cluster_ids``), and a union that
    # guesses would parse a ShiftTime as a RemoveEvent and silently delete the
    # events the scenario meant to move.
    interventions: list[
        Annotated[
            AddEvent | RemoveEvent | ShiftTime | ReplaceActor,
            Field(discriminator="kind"),
        ]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_scenario(self) -> Scenario:
        if not self.author.strip():
            raise ValueError("a scenario must record who posed it")
        if not self.interventions:
            raise ValueError("a scenario with no interventions is just the baseline")
        return self

    @staticmethod
    def build_id(name: str, cutoff_at: datetime) -> str:
        return stable_id("scn", name, cutoff_at.isoformat())


def apply_scenario(
    clusters: Sequence[EventCluster],
    index: EntityIndex,
    scenario: Scenario,
) -> tuple[list[EventCluster], EvidenceGraph]:
    """Apply every intervention in order and rebuild the graph.

    Order matters and is preserved: removing an event and then shifting it is
    an error the caller should see, not something to be silently reordered into
    working.
    """
    working = list(clusters)
    for intervention in scenario.interventions:
        working = intervention.apply(working, cutoff_at=scenario.cutoff_at)
    working.sort(key=lambda item: (item.window_start, item.cluster_id))
    graph = build_graph(working, index, cutoff_at=scenario.cutoff_at)
    log.info(
        "scenarios.applied",
        scenario=scenario.scenario_id,
        interventions=len(scenario.interventions),
        baseline_clusters=len(clusters),
        scenario_clusters=len(working),
    )
    return working, graph


class CandidateDelta(PramaanModel):
    """How one candidate moved between baseline and scenario."""

    candidate_key: str
    event_type: str
    baseline_score: float | None = None
    scenario_score: float | None = None

    @property
    def appeared(self) -> bool:
        return self.baseline_score is None and self.scenario_score is not None

    @property
    def disappeared(self) -> bool:
        return self.baseline_score is not None and self.scenario_score is None

    @property
    def delta(self) -> float:
        """Score change, treating absence as zero.

        Absence-as-zero is right for ranking the effect of a scenario but wrong
        for interpreting it: a candidate that appeared did not go from 0.0 to
        0.4, it went from *not proposed* to 0.4. :attr:`appeared` and
        :attr:`disappeared` are what distinguish the two, and reports should
        use them rather than the bare number.
        """
        return (self.scenario_score or 0.0) - (self.baseline_score or 0.0)


class ScenarioResult(PramaanModel):
    """The comparison between a baseline run and a scenario run."""

    scenario_id: str
    deltas: list[CandidateDelta] = Field(default_factory=list)

    @property
    def appeared(self) -> list[CandidateDelta]:
        return [delta for delta in self.deltas if delta.appeared]

    @property
    def disappeared(self) -> list[CandidateDelta]:
        return [delta for delta in self.deltas if delta.disappeared]

    @property
    def moved(self) -> list[CandidateDelta]:
        return sorted(
            (
                delta
                for delta in self.deltas
                if not delta.appeared and not delta.disappeared and abs(delta.delta) > 1e-9
            ),
            key=lambda item: (-abs(item.delta), item.candidate_key),
        )

    @property
    def unchanged_count(self) -> int:
        return len(self.deltas) - len(self.appeared) - len(self.disappeared) - len(self.moved)

    @property
    def interpretation(self) -> str:
        """The sentence that has to accompany any quoted scenario number."""
        return (
            "A scenario result describes how this pipeline responds to an assumed "
            "input. It is not a causal estimate and not a forecast: the assumed "
            "events did not happen, and no probability here is conditioned on "
            "evidence that they will."
        )


def diff_proposals(
    baseline: Sequence[CandidateProposal],
    scenario_proposals: Sequence[CandidateProposal],
    *,
    scenario_id: str,
) -> ScenarioResult:
    """Compare two proposal sets by candidate identity."""
    baseline_scores = {proposal.candidate_key: proposal.generator_score for proposal in baseline}
    scenario_scores = {
        proposal.candidate_key: proposal.generator_score for proposal in scenario_proposals
    }
    types = {proposal.candidate_key: proposal.hypothesis.event_type for proposal in baseline}
    types.update(
        {proposal.candidate_key: proposal.hypothesis.event_type for proposal in scenario_proposals}
    )

    deltas = [
        CandidateDelta(
            candidate_key=key,
            event_type=types[key],
            baseline_score=baseline_scores.get(key),
            scenario_score=scenario_scores.get(key),
        )
        for key in sorted(set(baseline_scores) | set(scenario_scores))
    ]
    return ScenarioResult(scenario_id=scenario_id, deltas=deltas)
