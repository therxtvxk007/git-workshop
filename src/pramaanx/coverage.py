"""How much evidence was actually observed, as opposed to assumed.

The bug this module exists to prevent produced a real forecast of 0.999975 from
six hours of GDELT. The base-rate estimator took its exposure from
``lookback_days`` -- a configuration constant -- and so estimated a 365-day rate
from a quarter of a day of evidence. The recorded rate came out at 0.118/day
against a true observed rate of 172/day: wrong by three orders of magnitude, in
a direction nothing in the pipeline could detect.

The underlying mistake is one every count-based estimator is exposed to.
Dividing events by an *assumed* window silently asserts that the window was
fully observed, which turns "we have no records here" into "no events happened
here". Those are different claims and only one of them is usually true.

So exposure becomes measured, and a run that cannot measure enough of it does
not produce a number. Abstention is the correct output of a forecaster that
lacks the evidence to forecast, and it is strictly more useful than a confident
one, because a reader can act on "we don't know" and cannot act on a number
whose error direction is unknown.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field

from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel
from pramaanx.schemas.observation import Observation

#: Fraction of the requested lookback that must actually be covered by evidence
#: before a rate over that lookback may be estimated. Not tuned -- chosen so a
#: run missing more than a fifth of its window abstains, and deliberately
#: exposed in configuration so a reviewer can argue with it.
DEFAULT_MIN_COVERAGE = 0.8


class SourceCoverage(PramaanModel):
    """What one source actually contributed, in time rather than in rows."""

    source_id: str
    observation_count: int = Field(ge=0)
    first_observed_at: UtcDatetime | None = None
    last_observed_at: UtcDatetime | None = None

    @property
    def observed_span_days(self) -> float:
        if self.first_observed_at is None or self.last_observed_at is None:
            return 0.0
        return (self.last_observed_at - self.first_observed_at).total_seconds() / 86400.0


class EvidenceCoverage(VersionedModel):
    """Whether a run had the evidence its configuration assumed it had.

    Attached to every forecast run. A reader who cannot see this cannot tell a
    low probability that means "unlikely" from one that means "we looked at six
    hours of a year and divided by the year".
    """

    cutoff_at: UtcDatetime
    requested_lookback_days: int = Field(gt=0)
    #: Span from the earliest to the latest evidence actually available at the
    #: cutoff. Not the requested window, and usually smaller.
    observed_span_days: float = Field(ge=0.0)
    observation_count: int = Field(ge=0)
    sources: tuple[SourceCoverage, ...] = ()
    min_coverage: float = Field(default=DEFAULT_MIN_COVERAGE, ge=0.0, le=1.0)

    @property
    def coverage_ratio(self) -> float:
        return min(self.observed_span_days / self.requested_lookback_days, 1.0)

    @property
    def sufficient(self) -> bool:
        return self.coverage_ratio >= self.min_coverage

    @property
    def effective_exposure_days(self) -> float:
        """The denominator a rate estimate may honestly use.

        The observed span, never the requested lookback. Zero when nothing was
        observed, which callers must treat as "cannot estimate" rather than
        dividing by it.
        """
        return self.observed_span_days

    def reason(self) -> str | None:
        """Why this run may not forecast, in terms a reader can act on."""
        if self.observation_count == 0:
            return (
                f"no evidence was available at {self.cutoff_at.isoformat()}. "
                "Nothing can be estimated from an empty corpus, and a rate of zero "
                "would assert that no events occurred rather than that none were seen."
            )
        if not self.sufficient:
            return (
                f"evidence covers {self.observed_span_days:.2f} of the "
                f"{self.requested_lookback_days} day lookback "
                f"({self.coverage_ratio:.1%}, minimum {self.min_coverage:.0%}). "
                "A rate estimated over a window that was not observed treats absent "
                "records as absent events, which is a different and usually false claim. "
                "Ingest a longer window, or lower generators.lookback_days to a period "
                "the evidence actually covers."
            )
        return None

    def manifest(self) -> dict[str, object]:
        """The block every run report carries."""
        return {
            "cutoff_at": self.cutoff_at.isoformat(),
            "requested_lookback_days": self.requested_lookback_days,
            "observed_span_days": round(self.observed_span_days, 4),
            "coverage_ratio": round(self.coverage_ratio, 4),
            "min_coverage": self.min_coverage,
            "sufficient": self.sufficient,
            "observation_count": self.observation_count,
            "reason": self.reason(),
            "sources": {
                source.source_id: {
                    "observations": source.observation_count,
                    "first_observed_at": (
                        source.first_observed_at.isoformat() if source.first_observed_at else None
                    ),
                    "last_observed_at": (
                        source.last_observed_at.isoformat() if source.last_observed_at else None
                    ),
                    "observed_span_days": round(source.observed_span_days, 4),
                }
                for source in sorted(self.sources, key=lambda item: item.source_id)
            },
        }


def measure_coverage(
    observations: Sequence[Observation],
    *,
    cutoff_at: datetime,
    lookback_days: int,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> EvidenceCoverage:
    """Measure what was actually available at a cutoff.

    Only evidence available *at or before* the cutoff counts, for the same
    reason the cutoff guard exists: a record that arrived afterwards could not
    have informed a forecast made then, however old the event it describes.

    The span is bounded below by the requested window's start, so ingesting five
    years of history for a one-year lookback reports full coverage rather than
    500%.
    """
    window_start = cutoff_at - timedelta(days=lookback_days)
    in_window = [
        item
        for item in observations
        if item.first_observed_at <= cutoff_at and item.first_observed_at >= window_start
    ]

    by_source: dict[str, list[datetime]] = {}
    for item in in_window:
        by_source.setdefault(item.source_id, []).append(item.first_observed_at)

    sources = tuple(
        SourceCoverage(
            source_id=source_id,
            observation_count=len(instants),
            first_observed_at=min(instants),
            last_observed_at=max(instants),
        )
        for source_id, instants in sorted(by_source.items())
    )

    if in_window:
        earliest = min(item.first_observed_at for item in in_window)
        latest = max(item.first_observed_at for item in in_window)
        span = (latest - earliest).total_seconds() / 86400.0
    else:
        span = 0.0

    return EvidenceCoverage(
        cutoff_at=cutoff_at,
        requested_lookback_days=lookback_days,
        observed_span_days=span,
        observation_count=len(in_window),
        sources=sources,
        min_coverage=min_coverage,
    )
