"""Timestamp verification.

A forecasting system stands or falls on its timestamps. Three things go wrong
in real feeds and all three are silent: a document dated in the future (clock
skew or a scheduled-publication field), a document whose retrieval precedes its
publication (a republished item carrying its original date), and a missing date
(which pandas-style pipelines cheerfully fill with `now`, making every historic
document look like breaking news).

Timezone handling is not decided here. `pramaan_x.timestamps` owns that, and
this module calls it, so Stage 0 and the availability rule cannot disagree
about what a naive stamp means -- which they used to, with Stage 0 winning
because it ran first.

A missing `retrieved_at` is counted and left missing. Filling it with
`published_at` would assert that the document was acquired the instant it
appeared, which is the most optimistic possible answer to the question a
backtest is actually asking; `pramaan_x.eval.availability` rejects such a
document from a backtest instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..timestamps import TimestampPolicy, resolve
from ..types import Document


@dataclass
class ValidationReport:
    n_input: int = 0
    n_missing_timestamp: int = 0
    n_future: int = 0
    n_retrieved_before_published: int = 0
    n_missing_retrieval: int = 0
    n_naive_timestamp: int = 0
    n_assumed_utc: int = 0
    n_ok: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> dict:
        return {"input": self.n_input, "ok": self.n_ok,
                "missing_timestamp": self.n_missing_timestamp,
                "future": self.n_future,
                "retrieved_before_published": self.n_retrieved_before_published,
                "missing_retrieval": self.n_missing_retrieval,
                "naive_timestamp": self.n_naive_timestamp,
                "assumed_utc": self.n_assumed_utc,
                "rejected": len(self.rejected)}


def validate_timestamps(
    docs: list[Document],
    *,
    now: datetime | None = None,
    require_timestamp: bool = True,
    max_future_skew_hours: int = 6,
    repair_retrieval: bool = True,
    policy: str | TimestampPolicy = TimestampPolicy.STRICT,
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

        # Timezone resolution, delegated. Under `strict` a naive stamp is
        # rejected with its reason preserved; under `assume_utc` it is read as
        # UTC and counted. Neither decision is made in this file.
        pub = resolve(d.published_at, policy, field="published_at")
        if pub.rejected:
            rep.n_naive_timestamp += 1
            rep.rejected.append((d.doc_id, pub.reason))
            continue
        rep.n_assumed_utc += int(pub.assumed_utc)
        d.published_at = pub.value

        if d.published_at > horizon:
            rep.n_future += 1
            rep.rejected.append((d.doc_id, f"published_at {d.published_at.isoformat()} beyond skew"))
            continue

        if d.retrieved_at is not None:
            ret = resolve(d.retrieved_at, policy, field="retrieved_at")
            if ret.rejected:
                rep.n_naive_timestamp += 1
                rep.rejected.append((d.doc_id, ret.reason))
                continue
            rep.n_assumed_utc += int(ret.assumed_utc)
            d.retrieved_at = ret.value
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
