"""Run lints: the rules a scored run must satisfy before its number counts.

The zero-probability lint is the one the plan's review had to repair (S27.1,
S32.2). The paper says no row may carry ``p_occ = 0``; the ladder's first rung
predicts exactly zero. Both are right, and the resolution is to scope the lint
to a declared diagnostic rather than to replace the comparator with an epsilon
-- which would change what the comparator is and therefore what its score
means.

The second rule is subtler and it is the one that actually bites. A rare-event
model that draws two thousand paths and sees no positive one reports an
empirical frequency of zero. That is a sampling limit, not a claim of
impossibility, and reporting it as ``p = 0`` would convert one into the other.
So a Monte Carlo zero is permitted, and required to carry its uncertainty.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pramaanx.core.errors import ContractViolationError
from pramaanx.models.capabilities import CapabilityManifest
from pramaanx.models.samples import ProbabilityMethod, WindowForecast


@dataclass(frozen=True)
class LintFinding:
    rule: str
    district_id: str
    family: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.district_id}/{self.family}: {self.detail}"


@dataclass(frozen=True)
class LintReport:
    findings: tuple[LintFinding, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.findings

    def raise_if_dirty(self) -> None:
        if self.clean:
            return
        head = "; ".join(str(finding) for finding in self.findings[:5])
        more = "" if len(self.findings) <= 5 else f" (+{len(self.findings) - 5} more)"
        raise ContractViolationError(f"run lint failed: {head}{more}")

    def to_dict(self) -> dict[str, object]:
        return {
            "clean": self.clean,
            "findings": [
                {
                    "rule": finding.rule,
                    "district_id": finding.district_id,
                    "family": finding.family,
                    "detail": finding.detail,
                }
                for finding in self.findings
            ],
        }


def check_no_hard_zero(
    forecasts: Sequence[WindowForecast], *, capabilities: CapabilityManifest
) -> LintReport:
    """No analytic zero probability, unless this is the declared zero baseline.

    A Monte Carlo zero is not a hard zero and passes; it is checked separately
    by :func:`check_monte_carlo_zeros`, which requires it to carry an interval.
    """
    if capabilities.diagnostic_zero_baseline:
        return LintReport()

    findings = [
        LintFinding(
            rule="hard_zero_probability",
            district_id=forecast.key.district_id,
            family=forecast.key.family,
            detail=(
                "the model asserts occurrence is impossible; 'unknown' is a "
                "display state, an impossibility claim is not"
            ),
        )
        for forecast in forecasts
        if forecast.method is ProbabilityMethod.ANALYTIC and forecast.p_occ == 0.0
    ]
    return LintReport(tuple(findings))


def check_monte_carlo_zeros(
    forecasts: Sequence[WindowForecast], *, min_draws: int = 100
) -> LintReport:
    """A sampled zero must come with enough draws to mean anything.

    With a true probability of 0.001 and a thousand draws, seeing no positive
    draw has probability about 0.368. With ten draws it says almost nothing.
    The rule-of-three upper bound is reported alongside, so a reader can see
    what the sample actually rules out (S32.2).
    """
    findings = [
        LintFinding(
            rule="undersampled_zero",
            district_id=forecast.key.district_id,
            family=forecast.key.family,
            detail=(
                f"no positive draw in {forecast.n_draws}, which only bounds the "
                f"probability below {3.0 / max(forecast.n_draws, 1):.4f}"
            ),
        )
        for forecast in forecasts
        # Analytic forecasts are exempt: they have no sampling error, so a
        # zero from one is an assertion, and check_no_hard_zero is the rule
        # that applies to it.
        if forecast.method is ProbabilityMethod.MONTE_CARLO
        and forecast.p_occ_mc == 0.0
        and forecast.n_draws < min_draws
    ]
    return LintReport(tuple(findings))


def check_coherence(forecasts: Sequence[WindowForecast]) -> LintReport:
    """``p_occ == 1 - P(N = 0)`` for every row, within its own uncertainty."""
    findings: list[LintFinding] = []
    for forecast in forecasts:
        try:
            forecast.check_coherence()
        except ContractViolationError as error:
            findings.append(
                LintFinding(
                    rule="occurrence_count_incoherence",
                    district_id=forecast.key.district_id,
                    family=forecast.key.family,
                    detail=error.message,
                )
            )
    return LintReport(tuple(findings))


def check_nested_windows(
    narrow: Sequence[WindowForecast], wide: Sequence[WindowForecast]
) -> LintReport:
    """``P(N_narrow > 0) <= P(N_wide > 0)`` when one window contains the other.

    Free for a daily-path model, because the wider window sums a superset of
    days. Independent per-horizon heads violate it, and this is where that
    shows up rather than in a reader's disbelief (S32.1).
    """
    by_key = {forecast.key.as_tuple(): forecast for forecast in wide}
    findings: list[LintFinding] = []
    for forecast in narrow:
        counterpart = by_key.get(forecast.key.as_tuple())
        if counterpart is None:
            continue
        slack = 3.0 * max(forecast.mc_standard_error, counterpart.mc_standard_error)
        if forecast.p_occ > counterpart.p_occ + slack:
            findings.append(
                LintFinding(
                    rule="nested_window_incoherence",
                    district_id=forecast.key.district_id,
                    family=forecast.key.family,
                    detail=(
                        f"narrow window p={forecast.p_occ:.4f} exceeds wide window "
                        f"p={counterpart.p_occ:.4f}"
                    ),
                )
            )
    return LintReport(tuple(findings))


def run_all(forecasts: Sequence[WindowForecast], *, capabilities: CapabilityManifest) -> LintReport:
    """Every per-forecast lint, combined into one report."""
    reports: Iterable[LintReport] = (
        check_no_hard_zero(forecasts, capabilities=capabilities),
        check_monte_carlo_zeros(forecasts),
        check_coherence(forecasts),
    )
    return LintReport(tuple(finding for report in reports for finding in report.findings))
