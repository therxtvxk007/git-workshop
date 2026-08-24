"""Precursor identification: which documents drove a forecast.

Section 3.4 of the survey treats evidence gathering as a separate pipeline stage
(SER, DeepQA-style passage scoring) bolted on after prediction. The problem with
that shape is that the retrieved evidence need not be what the model actually
responded to -- it is a plausible-looking justification produced by a different
system.

Here the attribution is the pooling gradient ``dS/ds_i = beta_b * alpha_i``,
computed in closed form from the fitted model. If an article has weight 0.4, the
forecast score genuinely moves at that rate with its instance score. Evidence and
mechanism are the same object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .features import instance_matrix
from .schema import BagGroup, Precursor

if TYPE_CHECKING:  # pragma: no cover
    from .stacking import HybridEventPredictor


def extract_precursors(
    predictor: "HybridEventPredictor",
    group: BagGroup,
    top_k: int = 5,
    min_weight: float = 1e-4,
) -> list[Precursor]:
    """Top-``k`` documents by attribution weight for one forecasting unit.

    Weight is ``attribution * sign-corrected instance score``: a document that
    the pooling attends to but which argues *against* the event should not be
    presented as supporting evidence for it.
    """
    from .stacking import to_pooled

    if predictor.mil is None:
        return []
    _, docs = instance_matrix(group, predictor.config.decay)
    if not docs:
        return []

    pooled = to_pooled(group, predictor.config.decay)
    weights = predictor.mil.attributions(pooled)
    scores = predictor.mil.instance_scores(pooled)
    if weights.size != len(docs):  # defensive: dimensionality drift
        return []

    # Contribution of instance i to the group score, relative to the mean.
    contribution = weights * (scores - float(np.mean(scores)))
    order = np.argsort(-contribution)

    precursors: list[Precursor] = []
    for i in order[: max(0, top_k)]:
        if weights[i] < min_weight:
            continue
        doc = docs[i]
        precursors.append(
            Precursor(
                doc_id=doc.doc_id,
                region=doc.region,
                date=doc.date,
                score=float(weights[i]),
                snippet=_best_snippet(doc),
                events=list(doc.events),
            )
        )
    return precursors


def _best_snippet(doc) -> str:
    """The sentence carrying the most conflictual extracted event."""
    if doc.events:
        strongest = min(doc.events, key=lambda e: e.polarity * e.confidence)
        if strongest.quote:
            return strongest.quote
    return doc.text[:240]


def precursor_report(forecast, max_items: int = 5) -> str:
    """Human-readable evidence block for one forecast."""
    lines = [
        f"Forecast  region={forecast.region}  origin={forecast.origin}  "
        f"horizon={forecast.horizon_days}d",
        f"  probability = {forecast.probability:.3f}"
        + (f"   (truth: {forecast.label})" if forecast.label is not None else ""),
        f"  conformal set = {set(forecast.conformal_set) or '{}'}"
        + ("   [ABSTAIN]" if forecast.abstained else ""),
    ]
    if not forecast.precursors:
        lines.append("  no precursor evidence recovered")
        return "\n".join(lines)
    lines.append(f"  top precursors (attribution weight):")
    for p in forecast.precursors[:max_items]:
        actions = ", ".join(sorted({e.action for e in p.events})[:4]) or "-"
        lines.append(f"    {p.date}  w={p.score:.3f}  [{actions}]")
        lines.append(f"      {p.snippet[:150]}")
    return "\n".join(lines)


def aggregate_precursor_actions(forecasts, top_n: int = 15) -> list[tuple[str, float]]:
    """Which event predicates carry attribution mass across many forecasts.

    A coarse global explanation: if ``strike`` and ``crackdown`` dominate while
    ``negotiate`` is absent, the model has learned a recognisable escalation
    signature rather than a spurious correlate.
    """
    mass: dict[str, float] = {}
    for f in forecasts:
        for p in f.precursors:
            for e in p.events:
                mass[e.action] = mass.get(e.action, 0.0) + p.score * abs(e.polarity)
    return sorted(mass.items(), key=lambda kv: -kv[1])[:top_n]
