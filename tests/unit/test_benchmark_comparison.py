"""The gates between "a bigger number" and "exceeded".

Every test here that asserts ``exceeded is False`` is the point of the module.
The one test that asserts ``True`` exists to prove the gates can be satisfied at
all -- a validator that never passes is as useless as one that always does.
"""

from __future__ import annotations

import pytest

from fixtures.benchmarks.harness import (
    make_run,
    paired_unit_scores,
    synthetic_contract,
)
from pramaanx.benchmarks.comparison import (
    ComparisonError,
    check_tolerances,
    compare,
    control_reproduced,
)
from pramaanx.benchmarks.schemas import (
    BenchmarkStatus,
    MetricDirection,
    PublishedScore,
    ScoreScale,
    SourceKind,
    SourceReference,
    Tolerance,
)

CONTROL_UNITS, CHALLENGER_UNITS = paired_unit_scores(count=40, lift=0.03)


def control_run(contract=None, **overrides):
    contract = contract or synthetic_contract()
    return make_run(
        contract,
        seed=11,
        metrics={"average_precision": 0.402, "brier_score": 0.049},
        per_unit={"average_precision": CONTROL_UNITS},
        role="control",
        **overrides,
    )


def challenger_run(contract=None, seed=23, units=None, **overrides):
    contract = contract or synthetic_contract()
    return make_run(
        contract,
        seed=seed,
        metrics={"average_precision": 0.432, "brier_score": 0.048},
        per_unit={"average_precision": units if units is not None else CHALLENGER_UNITS},
        role="challenger",
        **overrides,
    )


def challengers(contract=None, count=3):
    return [challenger_run(contract, seed=seed) for seed in (23, 37, 53)[:count]]


class TestTolerance:
    def test_a_run_inside_tolerance_reproduces(self) -> None:
        contract = synthetic_contract()
        assert control_reproduced(contract, control_run(contract))

    def test_a_run_outside_tolerance_does_not(self) -> None:
        contract = synthetic_contract()
        run = make_run(contract, metrics={"average_precision": 0.10, "brier_score": 0.05})
        assert not control_reproduced(contract, run)

    def test_a_missing_metric_is_not_a_zero(self) -> None:
        # Reporting 0.0 for a metric the parser dropped would read as a real
        # score -- and for a lower-is-better metric, as a perfect one.
        contract = synthetic_contract()
        run = make_run(contract, metrics={"brier_score": 0.049})
        checks = {check.metric: check for check in check_tolerances(contract, run)}
        assert checks["average_precision"].observed is None
        assert checks["average_precision"].within_tolerance is False

    def test_a_metric_with_no_tolerance_cannot_match(self) -> None:
        contract = synthetic_contract(
            reproduction_tolerance={"average_precision": Tolerance(absolute=0.01)}
        )
        checks = {
            check.metric: check for check in check_tolerances(contract, control_run(contract))
        }
        assert checks["brier_score"].within_tolerance is False
        assert "no tolerance declared" in (checks["brier_score"].note or "")

    def test_a_percentage_published_score_is_normalised(self) -> None:
        contract = synthetic_contract(
            primary_metric="hit_at_1",
            secondary_metrics=[],
            metric_direction={"hit_at_1": MetricDirection.HIGHER_IS_BETTER},
            published_score=[
                PublishedScore(
                    metric="hit_at_1",
                    value=41.16,
                    scale=ScoreScale.PERCENTAGE,
                    source=SourceReference(kind=SourceKind.PAPER, citation="table 2"),
                    verified_against_primary=True,
                )
            ],
            reproduction_tolerance={"hit_at_1": Tolerance(absolute=0.005)},
        )
        run = make_run(contract, metrics={"hit_at_1": 0.4130})
        checks = list(check_tolerances(contract, run))
        assert checks[0].within_tolerance

    def test_a_control_with_nothing_to_check_has_not_reproduced(self) -> None:
        contract = synthetic_contract(published_score=[])
        assert not control_reproduced(contract, control_run(contract))


class TestExceededGate:
    def test_a_genuine_improvement_passes_every_gate(self) -> None:
        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        assert result.exceeded, result.gate_details
        assert result.verdict is BenchmarkStatus.EXCEEDED
        assert result.failed_gates() == []

    def test_a_better_number_without_statistical_support_is_not_exceeded(self) -> None:
        # Negative control 11. The challenger's mean is higher, but the paired
        # interval on the per-unit difference includes zero.
        contract = synthetic_contract()
        noisy_control, _ = paired_unit_scores(count=40, jitter=0.20)
        noisy_challenger = [
            value + (0.15 if index % 2 else -0.14) for index, value in enumerate(noisy_control)
        ]
        result = compare(
            contract,
            control_run(contract).model_copy(
                update={"per_unit_scores": {"average_precision": noisy_control}}
            ),
            [challenger_run(contract, seed=seed, units=noisy_challenger) for seed in (23, 37, 53)],
        )
        assert not result.exceeded
        assert "interval_excludes_no_improvement" in result.failed_gates()

    def test_a_challenger_on_different_units_cannot_be_compared(self) -> None:
        # Negative control 12.
        contract = synthetic_contract()
        others = [
            challenger_run(contract, seed=seed).model_copy(
                update={"unit_ids": [f"other-{index}" for index in range(24)]}
            )
            for seed in (23, 37, 53)
        ]
        result = compare(contract, control_run(contract), others)
        assert not result.exceeded
        assert "identical_units" in result.failed_gates()

    def test_a_challenger_scored_by_different_metric_code_is_refused(self) -> None:
        contract = synthetic_contract()
        others = [
            challenger_run(contract, seed=seed).model_copy(
                update={"metric_code_hash": "sha256:" + "9" * 64}
            )
            for seed in (23, 37, 53)
        ]
        result = compare(contract, control_run(contract), others)
        assert "identical_metric_code" in result.failed_gates()

    def test_a_challenger_on_a_different_split_is_refused(self) -> None:
        contract = synthetic_contract()
        others = [
            challenger_run(contract, seed=seed).model_copy(
                update={"split_hash": "sha256:" + "8" * 64}
            )
            for seed in (23, 37, 53)
        ]
        assert "identical_split" in compare(contract, control_run(contract), others).failed_gates()

    def test_an_unreproduced_control_blocks_the_claim(self) -> None:
        # Negative control 1, at comparison time: nothing can be exceeded until
        # the control has reproduced.
        contract = synthetic_contract()
        weak = control_run(contract).model_copy(
            update={"parsed_metrics": {"average_precision": 0.10, "brier_score": 0.049}}
        )
        result = compare(contract, weak, challengers(contract))
        assert not result.exceeded
        assert "control_reproduced" in result.failed_gates()

    def test_too_few_seeds_blocks_the_claim(self) -> None:
        contract = synthetic_contract(minimum_seed_count=3)
        result = compare(contract, control_run(contract), challengers(contract, count=1))
        assert not result.exceeded
        assert "minimum_seeds" in result.failed_gates()

    def test_post_test_tuning_invalidates_rather_than_merely_refusing(self) -> None:
        # Negative control 14: a different verdict from "not exceeded".
        contract = synthetic_contract()
        tuned = [
            run.model_copy(update={"post_test_changes": ["config:prompt"]})
            for run in challengers(contract)
        ]
        result = compare(contract, control_run(contract), tuned)
        assert result.verdict is BenchmarkStatus.INVALIDATED
        assert "no_post_test_tuning" in result.failed_gates()

    def test_a_regression_in_the_wrong_direction_is_refused(self) -> None:
        contract = synthetic_contract()
        worse = [
            challenger_run(contract, seed=seed).model_copy(
                update={"parsed_metrics": {"average_precision": 0.20, "brier_score": 0.048}}
            )
            for seed in (23, 37, 53)
        ]
        result = compare(contract, control_run(contract), worse)
        assert "primary_metric_improved" in result.failed_gates()

    def test_a_secondary_regression_blocks_the_claim(self) -> None:
        # An improvement bought by a regression elsewhere is a trade, not an
        # advance, so the control's own secondary check must hold.
        contract = synthetic_contract()
        control = control_run(contract).model_copy(
            update={"parsed_metrics": {"average_precision": 0.402, "brier_score": 0.40}}
        )
        result = compare(contract, control, challengers(contract))
        assert "secondary_protections" in result.failed_gates()

    def test_missing_per_unit_scores_prevent_the_interval(self) -> None:
        contract = synthetic_contract()
        without = [
            challenger_run(contract, seed=seed).model_copy(update={"per_unit_scores": {}})
            for seed in (23, 37, 53)
        ]
        result = compare(contract, control_run(contract), without)
        assert not result.exceeded
        assert "interval_excludes_no_improvement" in result.failed_gates()
        assert any("statistical support" in detail for detail in result.gate_details)

    def test_a_lower_is_better_metric_improves_downward(self) -> None:
        contract = synthetic_contract(
            primary_metric="brier_score",
            secondary_metrics=[],
            published_score=[
                PublishedScore(
                    metric="brier_score",
                    value=0.050,
                    scale=ScoreScale.FRACTION,
                    source=SourceReference(kind=SourceKind.PAPER, citation="t"),
                    verified_against_primary=True,
                )
            ],
            reproduction_tolerance={"brier_score": Tolerance(absolute=0.01)},
        )
        control_units = [0.05 + 0.001 * (index % 7) for index in range(40)]
        challenger_units = [value - 0.01 for value in control_units]
        control = make_run(
            contract,
            seed=11,
            metrics={"brier_score": 0.049},
            per_unit={"brier_score": control_units},
        )
        others = [
            make_run(
                contract,
                seed=seed,
                metrics={"brier_score": 0.039},
                per_unit={"brier_score": challenger_units},
                role="challenger",
            )
            for seed in (23, 37, 53)
        ]
        result = compare(contract, control, others)
        assert result.exceeded, result.gate_details
        assert result.improvement is not None and result.improvement > 0


class TestComparisonErrors:
    def test_no_primary_metric_is_refused(self) -> None:
        contract = synthetic_contract(primary_metric=None)
        with pytest.raises(ComparisonError, match="no primary metric"):
            compare(contract, control_run(), challengers())

    def test_no_direction_is_refused(self) -> None:
        contract = synthetic_contract(metric_direction={})
        with pytest.raises(ComparisonError, match="no direction"):
            compare(contract, control_run(), challengers())

    def test_no_challenger_is_refused(self) -> None:
        with pytest.raises(ComparisonError, match="no challenger"):
            compare(synthetic_contract(), control_run(), [])


class TestComparisonRecord:
    def test_records_the_interval_effect_and_p_value(self) -> None:
        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        assert result.confidence_interval is not None
        assert result.p_value is not None
        assert result.seed_count == 3

    def test_is_deterministic(self) -> None:
        contract = synthetic_contract()
        first = compare(contract, control_run(contract), challengers(contract))
        second = compare(contract, control_run(contract), challengers(contract))
        assert first.canonical_dict() == second.canonical_dict()

    def test_serialises_to_canonical_json(self) -> None:
        from pramaanx.hashing import canonical_json

        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        assert canonical_json(result.canonical_dict())

    def test_every_declared_gate_is_present(self) -> None:
        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        assert {
            "control_reproduced",
            "identical_units",
            "identical_metric_code",
            "identical_split",
            "no_post_test_tuning",
            "minimum_seeds",
            "primary_metric_improved",
            "interval_excludes_no_improvement",
            "secondary_protections",
        } == set(result.gates)

    def test_a_refusal_always_says_why(self) -> None:
        contract = synthetic_contract(minimum_seed_count=9)
        result = compare(contract, control_run(contract), challengers(contract))
        assert not result.exceeded
        assert result.gate_details


class TestRendering:
    """The human rendering must not be able to say less than the JSON."""

    def build_report(self, **kwargs):
        from pramaanx.benchmarks.reporting import benchmark_report

        contract = synthetic_contract()
        runs = [
            control_run(contract),
            *challengers(contract),
            make_run(contract, seed=71, exit_code=1),
        ]
        return (
            contract,
            runs,
            benchmark_report(
                contract,
                runs,
                comparison=compare(contract, control_run(contract), challengers(contract)),
                **kwargs,
            ),
        )

    def test_render_benchmark_shows_runs_costs_and_the_comparison(self) -> None:
        from pramaanx.benchmarks.reporting import render_benchmark

        _, _, report = self.build_report()
        text = render_benchmark(report)
        assert "published scores" in text
        assert "GPU-h" in text
        assert "total cost" in text
        assert "comparison:" in text
        assert "FAILED" in text

    def test_render_benchmark_shows_blockers_and_notes(self) -> None:
        from pramaanx.benchmarks.reporting import benchmark_report, render_benchmark
        from pramaanx.benchmarks.schemas import Blocker, BlockerCode

        contract = synthetic_contract(
            blockers=[
                Blocker(
                    field="data_hash",
                    code=BlockerCode.DATA_UNAVAILABLE,
                    detail="not obtained",
                )
            ],
            notes=["a note worth keeping"],
        )
        text = render_benchmark(benchmark_report(contract, []))
        assert "blockers (1)" in text
        assert "a note worth keeping" in text

    def test_render_benchmark_reports_unverified_published_scores(self) -> None:
        from pramaanx.benchmarks.reporting import benchmark_report, render_benchmark

        contract = synthetic_contract(
            published_score=[
                PublishedScore(
                    metric="average_precision",
                    value=0.4,
                    scale=ScoreScale.FRACTION,
                    source=SourceReference(kind=SourceKind.PAPER, citation="t"),
                    verified_against_primary=False,
                )
            ]
        )
        text = render_benchmark(benchmark_report(contract, []))
        assert "NOT verified" in text
        assert "unverified" in text

    def test_render_benchmark_handles_a_contract_with_no_published_scores(self) -> None:
        from pramaanx.benchmarks.reporting import benchmark_report, render_benchmark

        text = render_benchmark(benchmark_report(synthetic_contract(published_score=[]), []))
        assert "none recorded" in text

    def test_render_benchmark_surfaces_validation_errors(self) -> None:
        from pramaanx.benchmarks.reporting import benchmark_report, render_benchmark
        from pramaanx.benchmarks.verification import validate_contract

        contract = synthetic_contract(seed_list=[])
        text = render_benchmark(benchmark_report(contract, [], validate_contract(contract)))
        assert "validation errors" in text

    def test_render_benchmark_flags_post_test_changes_and_reruns(self) -> None:
        from pramaanx.benchmarks.reporting import benchmark_report, render_benchmark

        contract = synthetic_contract()
        run = make_run(contract).model_copy(
            update={"post_test_changes": ["config:x"], "is_rerun_of": "brun_earlier"}
        )
        text = render_benchmark(benchmark_report(contract, [run]))
        assert "POST-TEST CHANGES" in text
        assert "rerun of brun_earlier" in text

    def test_render_comparison_lists_every_gate(self) -> None:
        from pramaanx.benchmarks.reporting import render_comparison

        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        text = render_comparison(result.canonical_dict())
        for gate in result.gates:
            assert gate in text
        assert "PASS" in text

    def test_render_comparison_shows_an_undefined_effect_size(self) -> None:
        from pramaanx.benchmarks.reporting import render_comparison

        contract = synthetic_contract()
        result = compare(contract, control_run(contract), challengers(contract))
        payload = result.canonical_dict()
        payload["effect_size"] = None
        assert "undefined" in render_comparison(payload)

    def test_render_registry_table_counts_by_status(self) -> None:
        from pramaanx.benchmarks.registry import BenchmarkRegistry
        from pramaanx.benchmarks.reporting import registry_report, render_registry_table

        registry = BenchmarkRegistry(contracts=[synthetic_contract()])
        text = render_registry_table(registry_report(registry, registry.validate_all()))
        assert "by status:" in text
        assert "synthetic_fixture" in text

    def test_render_validation_lists_unmet_rules(self) -> None:
        from pramaanx.benchmarks.reporting import render_validation
        from pramaanx.benchmarks.verification import validate_contract

        contract = synthetic_contract(seed_list=[])
        text = render_validation({"synthetic_fixture": validate_contract(contract)})
        assert "INVALID" in text
        assert "seeds_required" in text
        assert "1 failing validation" in text

    def test_run_report_records_the_manifest_hash(self) -> None:
        from pramaanx.benchmarks.reporting import run_report

        contract = synthetic_contract()
        run = control_run(contract)
        assert run_report(contract, run)["manifest_hash"] == run.manifest_hash()
