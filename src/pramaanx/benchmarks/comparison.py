"""Deciding whether a challenger may be said to have exceeded a control.

"Exceeded" is the strongest claim this project can make about a model, so it is
the one with the most ways to be wrong. A bigger number in a table is not the
claim; it is one of eight conditions, and this module refuses the claim unless
every one of them holds:

1. the control reproduced the published score inside the declared tolerance;
2. the challenger was evaluated on exactly the same units;
3. the primary metric moved in the direction the contract calls better;
4. the paired confidence interval excludes no improvement;
5. the declared secondary protection conditions all pass;
6. at least the minimum number of seeds was run;
7. the test period and the metric code were identical between the two;
8. no post-test tuning is recorded against either run.

Each condition is evaluated independently and recorded in ``gates`` with its own
verdict, so a refusal can always say which gate refused and why. A comparison
that cannot name its refusal is not reviewable.

Where units can be paired -- and forecast units almost always can, because both
models scored the same districts in the same months -- the comparison is paired.
Falling back to an unpaired test on paired data is not a conservative choice; it
answers a different question.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pramaanx.benchmarks.schemas import (
    BenchmarkContract,
    BenchmarkStatus,
    ComparisonResult,
    MetricDirection,
    ReproductionRun,
    ToleranceCheck,
)
from pramaanx.benchmarks.statistics import (
    Interval,
    block_bootstrap_ci,
    derive_seed,
    paired_bootstrap_ci,
    paired_effect_size,
    paired_permutation_test,
)
from pramaanx.benchmarks.verification import direction_improves, signed_improvement

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class ComparisonError(ValueError):
    """A comparison was requested that cannot be made."""


def check_tolerances(
    contract: BenchmarkContract,
    run: ReproductionRun,
) -> Iterator[ToleranceCheck]:
    """Compare a run's metrics against the published values, metric by metric.

    A published score whose scale is a percentage is normalised to a fraction
    before comparison, so a Hit@1 of ``41.16`` in a paper and ``0.4116`` from a
    run are recognised as the same number rather than a catastrophic miss.

    A metric with a published score but no declared tolerance yields a check that
    is *not* within tolerance: the absence of a tolerance is a reason to refuse,
    never a reason to pass.
    """
    for score in contract.published_score:
        observed = run.parsed_metrics.get(score.metric)
        published = score.as_fraction()
        if observed is None:
            yield ToleranceCheck(
                metric=score.metric,
                published=published,
                observed=None,
                delta=None,
                within_tolerance=False,
                tolerance=contract.reproduction_tolerance.get(score.metric),
                note="the run produced no value for this metric",
            )
            continue
        tolerance = contract.reproduction_tolerance.get(score.metric)
        if tolerance is None:
            yield ToleranceCheck(
                metric=score.metric,
                published=published,
                observed=observed,
                delta=abs(observed - published),
                within_tolerance=False,
                tolerance=None,
                note="no tolerance declared for this metric; a match cannot be asserted",
            )
            continue
        yield ToleranceCheck(
            metric=score.metric,
            published=published,
            observed=observed,
            delta=abs(observed - published),
            within_tolerance=tolerance.contains(published, observed),
            tolerance=tolerance,
            note=None
            if score.verified_against_primary
            else ("published value has not been verified against the primary source"),
        )


def control_reproduced(contract: BenchmarkContract, control: ReproductionRun) -> bool:
    """Whether the control run landed inside tolerance on every published metric.

    A control with no published metrics to check has not reproduced anything;
    it returns ``False`` rather than vacuously true.
    """
    checks = list(check_tolerances(contract, control))
    if not checks:
        return False
    return control.succeeded and all(check.within_tolerance for check in checks)


def _paired_unit_scores(
    contract: BenchmarkContract,
    control: ReproductionRun,
    challenger: ReproductionRun,
) -> tuple[list[float], list[float]]:
    """Per-unit scores for the primary metric, aligned by unit.

    Alignment is by the recorded ``unit_ids`` order, which both runs sort
    identically, so two runs over the same evaluation set line up regardless of
    the order their executors happened to emit them in.
    """
    metric = contract.primary_metric
    if metric is None:
        raise ComparisonError("contract names no primary metric")
    control_scores = control.per_unit_scores.get(metric)
    challenger_scores = challenger.per_unit_scores.get(metric)
    if not control_scores or not challenger_scores:
        raise ComparisonError(
            f"per-unit scores for {metric!r} are missing from "
            f"{'control' if not control_scores else 'challenger'}; a paired comparison "
            "needs both"
        )
    if len(control_scores) != len(challenger_scores):
        raise ComparisonError(
            f"{len(control_scores)} control units against {len(challenger_scores)} "
            "challenger units; these runs are not comparable"
        )
    return list(control_scores), list(challenger_scores)


def _interval(
    contract: BenchmarkContract,
    control_scores: Sequence[float],
    challenger_scores: Sequence[float],
    *,
    higher_is_better: bool,
    seed: int,
) -> Interval:
    """Build the confidence interval the contract asked for.

    A contract that declares a block length gets the block bootstrap: its units
    are temporally dependent, and the i.i.d. interval would be too narrow.
    """
    method = contract.confidence_method
    if method is None:
        raise ComparisonError("contract declares no confidence method")
    if method.block_length is not None:
        return block_bootstrap_ci(
            control_scores,
            challenger_scores,
            seed=seed,
            block_length=method.block_length,
            resamples=method.resamples,
            alpha=method.alpha,
            higher_is_better=higher_is_better,
        )
    return paired_bootstrap_ci(
        control_scores,
        challenger_scores,
        seed=seed,
        resamples=method.resamples,
        alpha=method.alpha,
        higher_is_better=higher_is_better,
    )


def compare(
    contract: BenchmarkContract,
    control: ReproductionRun,
    challengers: Sequence[ReproductionRun],
) -> ComparisonResult:
    """Evaluate every gate and return the verdict, with its reasons.

    Never raises on a failing gate: a refusal is a result, and the caller needs
    the whole gate table to explain it. It raises only when the comparison is
    malformed -- no primary metric, no challenger, mismatched unit counts -- which
    is a bug in the caller rather than a finding about the models.
    """
    metric = contract.primary_metric
    if metric is None:
        raise ComparisonError(f"{contract.benchmark_id}: no primary metric declared")
    direction = contract.direction_of(metric)
    if direction is None:
        raise ComparisonError(f"{contract.benchmark_id}: no direction declared for {metric!r}")
    if not challengers:
        raise ComparisonError(f"{contract.benchmark_id}: no challenger runs supplied")

    gates: dict[str, bool] = {}
    details: list[str] = []
    higher_is_better = direction is MetricDirection.HIGHER_IS_BETTER

    # 1. The control reproduced the published result.
    secondary_checks = list(check_tolerances(contract, control))
    gates["control_reproduced"] = control_reproduced(contract, control)
    if not gates["control_reproduced"]:
        missed = [check.metric for check in secondary_checks if not check.within_tolerance]
        details.append(
            "control run did not reproduce the published score within tolerance"
            + (f" (metrics outside tolerance: {', '.join(missed)})" if missed else "")
            + "; nothing can be said to have been exceeded until it does"
        )

    # 2. Identical evaluation units.
    control_units = control.unit_set_hash()
    same_units = all(run.unit_set_hash() == control_units for run in challengers)
    gates["identical_units"] = same_units
    if not same_units:
        details.append(
            "challenger and control were evaluated on different units; the difference "
            "between them is partly a difference of test set"
        )

    # 7. Identical test period and metric code.
    same_metric_code = all(run.metric_code_hash == control.metric_code_hash for run in challengers)
    same_split = all(run.split_hash == control.split_hash for run in challengers)
    gates["identical_metric_code"] = same_metric_code
    gates["identical_split"] = same_split
    if not same_metric_code:
        details.append("challenger and control were scored by different metric code")
    if not same_split:
        details.append("challenger and control used different splits")

    # 8. No post-test tuning.
    tuned = [run.run_id for run in (control, *challengers) if run.post_test_changes]
    gates["no_post_test_tuning"] = not tuned
    if tuned:
        details.append(
            f"post-test changes are recorded against {', '.join(tuned)}; the result is "
            "invalidated rather than merely unproven"
        )

    # 6. Enough seeds.
    seed_count = len({run.seed for run in challengers})
    required = contract.minimum_seed_count or 1
    gates["minimum_seeds"] = seed_count >= required
    if not gates["minimum_seeds"]:
        details.append(f"{seed_count} challenger seed(s) run, {required} required by the contract")

    # 3-4. Direction and interval, computed on the best-scoring challenger.
    control_score = control.parsed_metrics.get(metric)
    scored = [
        (run, run.parsed_metrics[metric]) for run in challengers if metric in run.parsed_metrics
    ]
    interval: Interval | None = None
    p_value: float | None = None
    effect: float | None = None
    improvement: float | None = None
    challenger_score: float | None = None

    if control_score is None or not scored:
        gates["primary_metric_improved"] = False
        gates["interval_excludes_no_improvement"] = False
        details.append(f"no {metric!r} value on the control or on any challenger run")
    else:
        best_run, challenger_score = max(
            scored,
            key=lambda pair: pair[1] if higher_is_better else -pair[1],
        )
        improvement = signed_improvement(direction, control_score, challenger_score)
        gates["primary_metric_improved"] = direction_improves(
            direction, control_score, challenger_score
        )
        if not gates["primary_metric_improved"]:
            details.append(
                f"{metric} moved from {control_score:.6g} to {challenger_score:.6g}, which is "
                f"not an improvement for a {direction.value} metric"
            )
        try:
            control_units_scores, challenger_units_scores = _paired_unit_scores(
                contract, control, best_run
            )
        except ComparisonError as error:
            gates["interval_excludes_no_improvement"] = False
            details.append(
                f"no paired interval could be computed: {error}. A numerically better "
                "score without statistical support is not 'exceeded'."
            )
        else:
            seed = derive_seed(contract.benchmark_id, control.run_id, best_run.run_id)
            interval = _interval(
                contract,
                control_units_scores,
                challenger_units_scores,
                higher_is_better=higher_is_better,
                seed=seed,
            )
            gates["interval_excludes_no_improvement"] = interval.excludes_no_improvement
            if not interval.excludes_no_improvement:
                details.append(
                    f"the {1 - interval.alpha:.0%} paired interval on the improvement is "
                    f"[{interval.lower:.6g}, {interval.upper:.6g}], which includes no "
                    "improvement"
                )
            effect = paired_effect_size(
                control_units_scores,
                challenger_units_scores,
                higher_is_better=higher_is_better,
            )
            if contract.paired_test is not None:
                test = paired_permutation_test(
                    control_units_scores,
                    challenger_units_scores,
                    seed=seed,
                    resamples=contract.paired_test.resamples,
                    alternative=contract.paired_test.alternative,
                    higher_is_better=higher_is_better,
                )
                p_value = test.p_value

    # 5. Secondary protection conditions.
    gates["secondary_protections"] = all(
        check.within_tolerance for check in secondary_checks if check.metric != metric
    )
    if not gates["secondary_protections"]:
        regressed = [
            check.metric
            for check in secondary_checks
            if check.metric != metric and not check.within_tolerance
        ]
        details.append(
            f"secondary protection failed on {', '.join(regressed)}; an improvement bought "
            "by a regression elsewhere is a trade, not an advance"
        )

    verdict = (
        BenchmarkStatus.EXCEEDED
        if all(gates.values())
        else BenchmarkStatus.INVALIDATED
        if tuned
        else BenchmarkStatus.CHALLENGED_NOT_EXCEEDED
    )

    return ComparisonResult(
        benchmark_id=contract.benchmark_id,
        contract_hash=contract.contract_hash(),
        control_run_id=control.run_id,
        challenger_run_ids=sorted(run.run_id for run in challengers),
        primary_metric=metric,
        metric_direction=direction,
        control_score=control_score,
        challenger_score=challenger_score,
        improvement=improvement,
        effect_size=effect,
        confidence_interval=(interval.lower, interval.upper) if interval else None,
        confidence_alpha=interval.alpha if interval else None,
        p_value=p_value,
        seed_count=seed_count,
        gates=gates,
        gate_details=details,
        secondary_checks=secondary_checks,
        verdict=verdict,
    )
