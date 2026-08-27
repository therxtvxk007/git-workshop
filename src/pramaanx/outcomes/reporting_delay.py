"""When a label may be believed.

An incident on the last day of a 30-day horizon is not in any dataset the
moment the horizon closes. ACLED publishes weekly; UCDP GED ships annually with
a candidate release in between. Scoring a fold the instant its horizon ends
therefore scores a window whose late incidents have not arrived, and every one
of those windows looks like a quiet district.

The correction is not to wait for "long enough". It is to state a delay per
dataset, measure the delay actually observed, and refuse to score any window
whose settle time has not passed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

#: Conservative defaults, in days, from each dataset's own publication cadence.
#: These are ceilings on the routine case, not on revisions -- a row corrected
#: eight months later is handled by ``label_revision``, not by waiting.
DEFAULT_DELAY_DAYS: Mapping[str, float] = {
    "acled": 14.0,
    "ucdp_ged": 400.0,
    "ucdp_candidate": 45.0,
}


class ReportingDelayError(ValueError):
    """A delay policy was asked about a dataset it does not cover."""


@dataclass(frozen=True)
class ReportingDelayPolicy:
    """Per-dataset delay, plus the settle time it implies for a window."""

    delays_days: Mapping[str, float]

    @classmethod
    def default(cls) -> ReportingDelayPolicy:
        return cls(delays_days=dict(DEFAULT_DELAY_DAYS))

    def delay_for(self, dataset: str) -> timedelta:
        if dataset not in self.delays_days:
            raise ReportingDelayError(
                f"no reporting delay declared for dataset {dataset!r}; "
                f"declared datasets are {sorted(self.delays_days)}. Defaulting to zero "
                "would treat an unpublished window as an empty one."
            )
        return timedelta(days=self.delays_days[dataset])

    def worst_delay(self, datasets: Iterable[str]) -> timedelta:
        """The binding delay when a panel is built from several datasets.

        The slowest dataset decides. A window is only fully reported once every
        contributing source has had time to report it; using the fastest would
        settle labels while a slower source is still filling them in.
        """
        names = sorted(set(datasets))
        if not names:
            raise ReportingDelayError("a panel needs at least one outcome dataset")
        return max(self.delay_for(name) for name in names)

    def settles_at(self, horizon_end: datetime, datasets: Iterable[str]) -> datetime:
        return horizon_end + self.worst_delay(datasets)


def observed_delay_days(
    pairs: Iterable[tuple[datetime, datetime]],
    *,
    quantile: float = 0.95,
) -> float | None:
    """The delay actually seen, from ``(occurred_at, first_resolvable_at)`` pairs.

    Reported alongside the declared policy so the two can be compared. A
    declared delay materially shorter than the observed one is a reason to
    change the policy, not a reason to score anyway -- but it can only prompt
    that if somebody measures it.
    """
    deltas = sorted(
        (resolvable - occurred).total_seconds() / 86400.0 for occurred, resolvable in pairs
    )
    if not deltas:
        return None
    if not 0.0 < quantile <= 1.0:
        raise ReportingDelayError("quantile must be in (0, 1]")
    if len(deltas) == 1:
        return deltas[0]
    if quantile == 0.5:
        return float(median(deltas))
    # Nearest-rank: no interpolation, so the answer is always a delay that was
    # actually observed rather than one between two observations.
    rank = max(1, min(len(deltas), int(-(-quantile * len(deltas) // 1))))
    return float(deltas[rank - 1])
