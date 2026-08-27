"""Candidate adjudication: from a proposal to a belief with an audit trail."""

from __future__ import annotations

from pramaanx.adjudication.adjudicator import (
    CONTRADICTION_WEIGHT,
    MIN_INDEPENDENT_SUPPORT,
    SUPPORT_WEIGHT,
    Adjudicator,
    EvidenceWeightAdjudicator,
    adjudicate_all,
)
from pramaanx.adjudication.base import (
    UNADJUDICATED,
    AdjudicationReport,
    BeliefState,
    BeliefUpdate,
    UpdateKind,
    Verdict,
    independence_counts,
)
from pramaanx.adjudication.math import logit, logit_mean, logit_spread, sigmoid

__all__ = [
    "CONTRADICTION_WEIGHT",
    "MIN_INDEPENDENT_SUPPORT",
    "SUPPORT_WEIGHT",
    "UNADJUDICATED",
    "AdjudicationReport",
    "Adjudicator",
    "BeliefState",
    "BeliefUpdate",
    "EvidenceWeightAdjudicator",
    "UpdateKind",
    "Verdict",
    "adjudicate_all",
    "independence_counts",
    "logit",
    "logit_mean",
    "logit_spread",
    "sigmoid",
]
