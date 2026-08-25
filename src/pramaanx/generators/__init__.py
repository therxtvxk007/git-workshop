"""Candidate generators.

A model cannot score a future event that never enters the candidate pool, so
discovery is a first-class stage with its own interface and its own metrics.

M0 ships G0 only. The build plan's G1-G7 (CRI temporal rules, neural TKG,
historical analogy, change-point/narrative diffusion, OpenForecaster,
causal/stakeholder scenarios, open-set anomalies) register through the same
interface, and the union stage is required to preserve which branch proposed
what.
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

__all__ = [
    "BaseGenerator",
    "BaseRateGenerator",
    "CandidateGenerator",
    "CandidateProposal",
    "ForecastContext",
    "RateEstimate",
    "available_generators",
    "epistemic_uncertainty",
    "estimate_rates",
    "get_generator_class",
    "parse_buckets",
    "register_generator",
    "seasonal_multiplier",
]
