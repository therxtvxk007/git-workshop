"""Predictive samples, and what a probability of zero is allowed to mean.

Two shapes, because two honest things a model can produce (S32.1, S42):

* :class:`PathSamples` -- draws of *daily* counts. Any window follows by
  summing days, so 7, 14, 28 and 30-day horizons come from one model, nested
  windows are coherent by construction, and the CAST comparator's Friday-
  aligned 28 days is reachable without a second fit.
* :class:`WindowSamples` -- draws of a total for *one contracted window*. What
  persistence and a rolling empirical distribution actually produce. Asking one
  of these for a different window, or for daily resolution, raises rather than
  redistributing the total under an assumption nobody stated.

The other half of this module is the rare-event arithmetic the plan spells out
(S32.2). With a true probability of 0.001 and a thousand draws, the chance of
seeing no positive draw is about 36.8%. So an empirical frequency of zero is
not evidence that a model assigns a hard zero, and reporting it as ``p = 0``
would turn a sampling limit into a claim of impossibility. Distribution
probability and sample frequency are therefore separate fields, the method is
recorded, and the Monte Carlo uncertainty travels with the number.

No epsilon, no clipping, no floor. A model that genuinely asserts zero says so
(that is ladder rung 1, and it is a declared diagnostic), and a model that
merely failed to sample one says something different.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np

from pramaanx.core.errors import CapabilityUnsupportedError, ContractViolationError
from pramaanx.hashing import utc_isoformat
from pramaanx.panel.windows import Window

#: Default PMF support. Beyond it the mass is reported as a single tail bucket,
#: which is enough to display and not enough to log-score an exact count.
DEFAULT_PMF_K = 10


class ProbabilityMethod(StrEnum):
    """How an occurrence probability was obtained. Recorded, never inferred."""

    #: Computed from the model's own distribution. Exact up to float error.
    ANALYTIC = "analytic"
    #: The fraction of draws with a positive count. Subject to sampling error,
    #: which is reported alongside it.
    MONTE_CARLO = "monte_carlo"


class DrawKind(StrEnum):
    """Which uncertainty a draw index belongs to.

    Predictive draws and measurement draws are different axes, and pairing them
    by a shared integer index is only correct if something says they are paired
    (S31.3). Naming the kind is the minimum that makes the question askable.
    """

    PREDICTIVE = "predictive"
    MEASUREMENT = "measurement"


@dataclass(frozen=True)
class PanelKey:
    """Which panel row a column of samples belongs to."""

    district_id: str
    family: str

    def as_tuple(self) -> tuple[str, str]:
        return (self.district_id, self.family)


@dataclass(frozen=True)
class WindowForecast:
    """One row's forecast for one window, with its own uncertainty declared."""

    key: PanelKey
    window: Window
    #: The occurrence probability this forecast asserts.
    p_occ: float
    method: ProbabilityMethod
    n_draws: int
    #: The empirical fraction of positive draws. Equal to ``p_occ`` for a
    #: sample-only model, and informative for an analytic one.
    p_occ_mc: float
    pmf: tuple[float, ...]
    tail_mass: float
    mean: float

    @property
    def mc_standard_error(self) -> float:
        """Binomial standard error of the sampled frequency.

        Zero for an analytic forecast, which has no sampling error at all. A
        degenerate model reporting a standard error computed from its own
        certainty would widen every downstream tolerance for no reason.
        """
        if self.method is ProbabilityMethod.ANALYTIC:
            return 0.0
        if self.n_draws <= 0:
            return float("nan")
        p = self.p_occ_mc
        return math.sqrt(max(p * (1.0 - p), 0.0) / self.n_draws)

    def mc_interval(self, *, z: float = 1.96) -> tuple[float, float]:
        """A Wald interval, widened by the rule-of-three when no draw was positive.

        With zero positives the Wald interval collapses to a point, which is
        exactly the misreading this module exists to prevent: it would say the
        model is certain when the sampler merely ran out of draws. The
        rule-of-three upper bound ``3/n`` is the honest replacement, clamped to
        one -- with very few draws ``3/n`` exceeds a probability.

        An analytic forecast gets a point interval, because its probability
        does not come from a sample and no interval around it would mean
        anything.
        """
        if self.method is ProbabilityMethod.ANALYTIC:
            return (self.p_occ, self.p_occ)
        if self.n_draws <= 0:
            return (float("nan"), float("nan"))
        rule_of_three = min(3.0 / self.n_draws, 1.0)
        if self.p_occ_mc == 0.0:
            return (0.0, rule_of_three)
        if self.p_occ_mc == 1.0:
            return (1.0 - rule_of_three, 1.0)
        half = z * self.mc_standard_error
        return (max(0.0, self.p_occ_mc - half), min(1.0, self.p_occ_mc + half))

    def quantile(self, level: float) -> int:
        """A count quantile from the PMF, tail included as its lower edge."""
        if not 0.0 <= level <= 1.0:
            raise ContractViolationError("quantile level must be in [0, 1]", level=level)
        cumulative = 0.0
        for count, mass in enumerate(self.pmf):
            cumulative += mass
            if cumulative >= level:
                return count
        return len(self.pmf)

    def check_coherence(self, *, tolerance: float = 1e-9) -> None:
        """``p_occ == 1 - P(N = 0)`` for the same distribution.

        Cheap, and it catches the failure where an occurrence head and a count
        head are fitted separately and then reported as one forecast.
        """
        implied = 1.0 - self.pmf[0]
        slack = (
            tolerance
            if self.method is ProbabilityMethod.ANALYTIC
            else 3.0 * (self.mc_standard_error or tolerance)
        )
        if abs(self.p_occ - implied) > max(slack, tolerance):
            raise ContractViolationError(
                "occurrence probability disagrees with the count distribution",
                p_occ=self.p_occ,
                implied=implied,
                method=str(self.method),
            )

    def to_dict(self) -> dict[str, object]:
        low, high = self.mc_interval()
        return {
            "district_id": self.key.district_id,
            "family": self.key.family,
            "window": self.window.to_dict(),
            "p_occ": self.p_occ,
            "probability_method": str(self.method),
            "p_occ_mc": self.p_occ_mc,
            "n_draws": self.n_draws,
            "mc_interval_low": low,
            "mc_interval_high": high,
            "pmf": list(self.pmf),
            "tail_mass": self.tail_mass,
            "mean": self.mean,
        }


def _summarise(
    counts: np.ndarray,
    *,
    key: PanelKey,
    window: Window,
    method: ProbabilityMethod,
    k: int,
    analytic_p_occ: float | None = None,
) -> WindowForecast:
    """Turn one row's window-total draws into a forecast."""
    if counts.ndim != 1:
        raise ContractViolationError("expected one dimension of draws", shape=list(counts.shape))
    n = int(counts.size)
    if n == 0:
        raise ContractViolationError("cannot summarise zero draws")
    p_mc = float(np.mean(counts > 0))
    # Clip into the tail bucket *before* counting. A bincount over raw counts
    # allocates an array as long as the largest draw, so one district with a
    # very large total would try to allocate gigabytes for a ten-bucket PMF.
    clipped = np.minimum(counts.astype(np.int64), k + 1)
    histogram = np.bincount(clipped, minlength=k + 2) / n
    pmf = tuple(float(value) for value in histogram[: k + 1])
    tail = float(histogram[k + 1])
    return WindowForecast(
        key=key,
        window=window,
        p_occ=p_mc if analytic_p_occ is None else analytic_p_occ,
        method=method,
        n_draws=n,
        p_occ_mc=p_mc,
        pmf=pmf,
        tail_mass=tail,
        mean=float(np.mean(counts)),
    )


@dataclass(frozen=True)
class WindowSamples:
    """Draws of a total for exactly one window. No daily resolution claimed."""

    keys: tuple[PanelKey, ...]
    window: Window
    #: ``[draw, panel_row]``, non-negative integers.
    counts: np.ndarray
    draw_kind: DrawKind = DrawKind.PREDICTIVE
    #: How the resulting probability should be read. A degenerate model -- one
    #: whose "draws" enumerate its whole distribution rather than sample from
    #: it -- declares ANALYTIC, because it has no sampling error and its zero
    #: is an assertion rather than a miss. Getting this wrong in either
    #: direction misfiles a lint: a sampled zero reported as analytic looks
    #: like a claim of impossibility, and an asserted zero reported as sampled
    #: escapes the rule that exists to catch it.
    method: ProbabilityMethod = ProbabilityMethod.MONTE_CARLO

    def __post_init__(self) -> None:
        _check_counts(self.counts, expected_dims=2, rows=len(self.keys))

    @property
    def n_draws(self) -> int:
        return int(self.counts.shape[0])

    def summarise(self, *, k: int = DEFAULT_PMF_K) -> tuple[WindowForecast, ...]:
        return tuple(
            _summarise(
                self.counts[:, index],
                key=key,
                window=self.window,
                method=self.method,
                k=k,
            )
            for index, key in enumerate(self.keys)
        )

    def aggregate(
        self, groups: dict[str, tuple[int, ...]], *, k: int = DEFAULT_PMF_K
    ) -> tuple[WindowForecast, ...]:
        """Sum draws within a group, then summarise. Never sum probabilities.

        A state's occurrence probability is the fraction of draws whose *state
        total* is positive. Summing district probabilities answers a different
        question and answers it wrongly (S4, S32.3).

        The arithmetic here is exact for whatever draws it is given. Whether
        the *result* is calibrated depends on whether those draws are jointly
        valid across districts, which is a model property the capability
        manifest declares and this method cannot supply.
        """
        out: list[WindowForecast] = []
        for name, indices in sorted(groups.items()):
            totals = self.counts[:, list(indices)].sum(axis=1, dtype=np.int64)
            out.append(
                _summarise(
                    totals,
                    key=PanelKey(district_id=name, family="aggregate"),
                    window=self.window,
                    method=self.method,
                    k=k,
                )
            )
        return tuple(out)


@dataclass(frozen=True)
class PathSamples:
    """Draws of daily counts, indexed ``[draw, panel_row, daily_bin]``.

    One array answers every horizon the contract asks for, and nested windows
    are coherent by construction: P(N7>0) <= P(N14>0) <= P(N30>0) holds because
    the later window contains the earlier one's days, not because a repair step
    enforced it.
    """

    keys: tuple[PanelKey, ...]
    #: Bin edges, ends included: ``len(edges) == n_days + 1``.
    edges: tuple[datetime, ...]
    counts: np.ndarray
    draw_kind: DrawKind = DrawKind.PREDICTIVE
    method: ProbabilityMethod = ProbabilityMethod.MONTE_CARLO

    def __post_init__(self) -> None:
        _check_counts(self.counts, expected_dims=3, rows=len(self.keys))
        if len(self.edges) != self.counts.shape[2] + 1:
            raise ContractViolationError(
                "daily edges must bound every bin",
                edges=len(self.edges),
                bins=int(self.counts.shape[2]),
            )
        if list(self.edges) != sorted(self.edges):
            raise ContractViolationError("daily edges must be increasing")

    @property
    def n_draws(self) -> int:
        return int(self.counts.shape[0])

    @property
    def horizon(self) -> Window:
        return Window(self.edges[0], self.edges[-1])

    def window(self, start: datetime, end: datetime) -> WindowSamples:
        """Totals over ``[start, end)``, refusing anything it cannot cover.

        Alignment and coverage are checked rather than approximated. Silently
        truncating a 90-day request to the 30 days available is the failure
        this method exists to make impossible.
        """
        requested = Window(start, end)
        if start < self.edges[0] or end > self.edges[-1]:
            raise CapabilityUnsupportedError(
                "requested window is outside this forecast's horizon",
                requested=requested.to_dict(),
                horizon=self.horizon.to_dict(),
            )
        try:
            first = self.edges.index(start)
            last = self.edges.index(end)
        except ValueError:
            raise ContractViolationError(
                "requested window does not align with the daily bin edges; the "
                "target contract and the model must share one calendar",
                requested=requested.to_dict(),
                first_edge=utc_isoformat(self.edges[0]),
            ) from None
        return WindowSamples(
            keys=self.keys,
            window=requested,
            counts=self.counts[:, :, first:last].sum(axis=2, dtype=np.int64),
            draw_kind=self.draw_kind,
            method=self.method,
        )


def _check_counts(counts: np.ndarray, *, expected_dims: int, rows: int) -> None:
    if counts.ndim != expected_dims:
        raise ContractViolationError(
            "unexpected sample array shape", expected_dims=expected_dims, shape=list(counts.shape)
        )
    if counts.shape[1] != rows:
        raise ContractViolationError(
            "sample columns do not match the panel keys",
            keys=rows,
            columns=int(counts.shape[1]),
        )
    if not np.issubdtype(counts.dtype, np.integer):
        raise ContractViolationError(
            "counts must be integers; a fractional count is an aggregate, not a "
            "draw from a count distribution",
            dtype=str(counts.dtype),
        )
    if counts.size and int(counts.min()) < 0:
        raise ContractViolationError("counts must be non-negative", minimum=int(counts.min()))
