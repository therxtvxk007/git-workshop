"""Timestamp verification.

A forecasting system stands or falls on its timestamps. Three things go wrong
in real feeds and all three are silent: a document dated in the future (clock
skew or a scheduled-publication field), a document whose retrieval precedes its
publication (a republished item carrying its original date), and a missing date
(which pandas-style pipelines cheerfully fill with `now`, making every historic
document look like breaking news).

A missing `retrieved_at` is counted and left missing. Filling it with
`published_at` would assert that the document was acquired the instant it
appeared, which is the most optimistic possible answer to the question a
backtest is actually asking; `pramaan_x.eval.availability` rejects such a
document from a backtest instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..types import Document


@dataclass
class ValidationReport:
    n_input: int = 0
    n_missing_timestamp: int = 0
    n_future: int = 0
    n_retrieved_before_published: int = 0
    n_missing_retrieval: int = 0
    n_ok: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> dict:
        return {"input": self.n_input, "ok": self.n_ok,
                "missing_timestamp": self.n_missing_timestamp,
                "future": self.n_future,
                "retrieved_before_published": self.n_retrieved_before_published,
                "missing_retrieval": self.n_missing_retrieval,
                "rejected": len(self.rejected)}


def validate_timestamps(
    docs: list[Document],
    *,
    now: datetime | None = None,
    require_timestamp: bool = True,
    max_future_skew_hours: int = 6,
    repair_retrieval: bool = True,
) -> tuple[list[Document], ValidationReport]:
    now = now or datetime.now(UTC)
    horizon = now + timedelta(hours=max_future_skew_hours)
    rep = ValidationReport(n_input=len(docs))
    kept: list[Document] = []

    for d in docs:
        if d.published_at is None:
            rep.n_missing_timestamp += 1
            if require_timestamp:
                rep.rejected.append((d.doc_id, "missing published_at"))
                continue
        elif d.published_at.tzinfo is None:
            d.published_at = d.published_at.replace(tzinfo=UTC)

        if d.published_at > horizon:
            rep.n_future += 1
            rep.rejected.append((d.doc_id, f"published_at {d.published_at.isoformat()} beyond skew"))
            continue

        if d.retrieved_at is not None:
            if d.retrieved_at.tzinfo is None:
                d.retrieved_at = d.retrieved_at.replace(tzinfo=UTC)
            if d.retrieved_at < d.published_at:
                rep.n_retrieved_before_published += 1
                if repair_retrieval:
                    # Trust publication, not retrieval: retrieval clocks are
                    # ours and drift; the publication date is the claim being
                    # made about when the information existed.
                    d.retrieved_at = d.published_at
                else:
                    rep.rejected.append((d.doc_id, "retrieved_at precedes published_at"))
                    continue
        else:
            # Left as None on purpose. See the module docstring: the
            # availability rule rejects it, and that rejection is the honest
            # answer, not a repaired timestamp.
            rep.n_missing_retrieval += 1

        rep.n_ok += 1
        kept.append(d)

    return kept, rep


def assert_no_future_evidence(docs: list[Document], origin: datetime) -> None:
    """Hard gate used at every forecast origin."""
    bad = [d.doc_id for d in docs if d.published_at >= origin]
    if bad:
        raise AssertionError(
            f"{len(bad)} documents at or after forecast origin {origin.isoformat()} "
            f"reached the evidence set (first: {bad[:3]})"
        )
