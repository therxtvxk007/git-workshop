"""Candidate generators.

A model cannot score a future event that never enters the candidate pool, so
discovery is a first-class stage with its own interface and its own metrics.

G0 (base rates and hazards) is the preregistered floor. G1 (temporal rules over
the evidence graph) is the first branch that has to clear it, and
:mod:`pramaanx.generators.comparison` makes that comparison a computation
rather than a claim in a report.

The remaining branches from the build plan -- neural TKG, historical analogy,
change-point and narrative diffusion, OpenForecaster, causal and stakeholder
scenarios, open-set anomalies -- register through the same interface. The union
stage is required to preserve which branch proposed what, because the candidate
oracle diagnostic depends on being able to attribute a miss to discovery rather
than to scoring.
"""

from __future__ import annotations

from pramaanx.generators.base import (
    BaseGenerator,
    CandidateGenerator,
    CandidateProposal,
    ForecastContext,
    available_generators,
    get_generator_class,
    register_generator,
)
from pramaanx.generators.base_rate import (
    BaseRateGenerator,
    RateEstimate,
    epistemic_uncertainty,
    estimate_rates,
    parse_buckets,
    seasonal_multiplier,
)
from pramaanx.generators.comparison import (
    DEFAULT_MARGIN,
    FLOOR_GENERATOR,
    DiscoveryComparison,
    FloorVerdict,
    compare_discovery,
)
from pramaanx.generators.temporal_rules import (
    ALL_RULES,
    RULE_DIFFUSION,
    RULE_ESCALATION,
    RULE_RECURRENCE,
    TemporalRuleGenerator,
)

__all__ = [
    "ALL_RULES",
    "DEFAULT_MARGIN",
    "FLOOR_GENERATOR",
    "RULE_DIFFUSION",
    "RULE_ESCALATION",
    "RULE_RECURRENCE",
    "BaseGenerator",
    "BaseRateGenerator",
    "CandidateGenerator",
    "CandidateProposal",
    "DiscoveryComparison",
    "FloorVerdict",
    "ForecastContext",
    "RateEstimate",
    "TemporalRuleGenerator",
    "available_generators",
    "compare_discovery",
    "epistemic_uncertainty",
    "estimate_rates",
    "get_generator_class",
    "parse_buckets",
    "register_generator",
    "seasonal_multiplier",
]
