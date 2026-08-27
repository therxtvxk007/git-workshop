"""Hypothetical scenarios and the counterfactual track.

Interventions edit a copy of the evidence -- assume an event, suppress one,
move one in time, swap one actor for another -- and the pipeline is re-run
against the result. Every artefact produced is marked hypothetical from the
cluster upward, and nothing writes back to the ledger or the snapshot.

The actor-replacement and time-shift interventions are the counterfactual track
the evaluation package names: a model that forecasts identically whichever
group is involved, or whenever the events happened, is keying on something
other than what it claims to be keying on.

One caveat travels with every result and is worth repeating outside the
docstring: a scenario shows how *this pipeline* responds to an assumed input.
It is not a causal estimate of how the world would respond.
"""

from __future__ import annotations

from pramaanx.scenarios.interface import (
    HYPOTHETICAL_PREFIX,
    AddEvent,
    CandidateDelta,
    Intervention,
    InterventionKind,
    RemoveEvent,
    ReplaceActor,
    Scenario,
    ScenarioResult,
    ShiftTime,
    apply_scenario,
    diff_proposals,
)

__all__ = [
    "HYPOTHETICAL_PREFIX",
    "AddEvent",
    "CandidateDelta",
    "Intervention",
    "InterventionKind",
    "RemoveEvent",
    "ReplaceActor",
    "Scenario",
    "ScenarioResult",
    "ShiftTime",
    "apply_scenario",
    "diff_proposals",
]
