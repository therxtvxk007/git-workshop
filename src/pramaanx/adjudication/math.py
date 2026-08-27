"""Log-odds arithmetic, kept in one place so the clamps are consistent.

Belief updates are additive in log-odds and not in probability: +0.1 means
something very different at 0.5 than at 0.9, so a log of probability steps
cannot be replayed. Everything here exists to make the replay in
:meth:`BeliefState.replay_probability` exact.
"""

from __future__ import annotations

import math

#: Probabilities are clamped away from 0 and 1 before any logit. Certainty is
#: not representable in log-odds, and this system is not entitled to it anyway:
#: a forecast of exactly 1.0 claims no evidence could ever change its mind.
EPSILON = 1e-9


def clamp(probability: float) -> float:
    """Bound a probability strictly inside (0, 1)."""
    return min(max(probability, EPSILON), 1.0 - EPSILON)


def logit(probability: float) -> float:
    value = clamp(probability)
    return math.log(value / (1.0 - value))


def sigmoid(value: float) -> float:
    # Branch to avoid overflow: exp(709) is near the float64 ceiling, and a
    # confident belief can carry a larger logit than that after enough updates.
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def logit_mean(probabilities: list[float]) -> float:
    """Average probabilities in logit space, then map back.

    Averaging probabilities directly pulls every aggregate toward 0.5 and
    systematically understates agreement between confident trials. Averaging in
    logit space is the aggregation the calibration literature assumes, and it is
    what makes trial disagreement comparable across the probability range.
    """
    if not probabilities:
        return 0.5
    return sigmoid(sum(logit(value) for value in probabilities) / len(probabilities))


def logit_spread(probabilities: list[float]) -> float:
    """Population standard deviation of the trials, in logit space.

    Reported rather than folded into the probability. A mean of 0.6 from trials
    that all said 0.6 and one from trials that said 0.1 and 0.95 are different
    claims, and only this number distinguishes them.
    """
    if len(probabilities) < 2:
        return 0.0
    values = [logit(value) for value in probabilities]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)
