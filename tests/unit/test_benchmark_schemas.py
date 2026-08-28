"""The contract models, and what they refuse to represent.

Most of these tests are about the model rejecting a state rather than storing
one. A schema that accepts a period ending before it starts, or a tolerance with
no bound, pushes the failure downstream to whoever reads it months later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fixtures.benchmarks.harness import COMMIT, make_run, synthetic_contract, synthetic_plan
from pramaanx.benchmarks.schemas import (
    BenchmarkStatus,
    Blocker,
    BlockerCode,
    HardwareRequirements,
    MetricDirection,
    Period,
    PublishedScore,
    RawRunResult,
    ScoreScale,
    SoftwareEnvironment,
    SourceKind,
    SourceReference,
    Tolerance,
)


class TestStatusEnum:
    def test_has_exactly_the_twelve_declared_states(self) -> None:
        assert [status.value for status in BenchmarkStatus] == [
            "not_started",
            "contract_incomplete",
            "blocked_data",
            "blocked_licence",
            "blocked_environment",
            "running",
            "reproduction_failed",
            "reproduced",
            "challenger_running",
            "challenged_not_exceeded",
            "exceeded",
            "invalidated",
        ]

    def test_code_exists_is_not_reproduced(self) -> None:
        # The distinction the enum exists for: they are different members, and
        # nothing maps one onto the other.
        assert BenchmarkStatus.NOT_STARTED is not BenchmarkStatus.REPRODUCED
        assert BenchmarkStatus.CONTRACT_INCOMPLETE is not BenchmarkStatus.REPRODUCED


class TestPeriod:
    def test_rejects_a_period_that_ends_before_it_starts(self) -> None:
        with pytest.raises(ValidationError, match="ends"):
            Period(start="2024-06-01", end="2024-01-01")

    def test_unknown_period_is_representable_and_incomplete(self) -> None:
        assert Period().is_complete is False

    def test_overlap_is_detected(self) -> None:
        train = Period(start="2020-01-01", end="2023-12-31")
        test = Period(start="2023-06-01", end="2024-12-31")
        assert train.overlaps(test)

    def test_unknown_periods_never_overlap(self) -> None:
        # Two unknown periods must not be reported as disjoint *or* overlapping;
        # returning False here means the split-disjointness rule stays silent
        # rather than asserting something about dates nobody has.
        assert Period().overlaps(Period(start="2020-01-01", end="2020-12-31")) is False


class TestTolerance:
    def test_requires_at_least_one_bound(self) -> None:
        with pytest.raises(ValidationError, match="absolute or a relative"):
            Tolerance()

    def test_absolute_bound(self) -> None:
        tolerance = Tolerance(absolute=0.01)
        assert tolerance.contains(0.400, 0.405)
        assert not tolerance.contains(0.400, 0.420)

    def test_relative_bound_is_ignored_against_a_published_zero(self) -> None:
        # Relative tolerance against zero is undefined; falling back to "not
        # within tolerance" is the fail-closed answer.
        assert Tolerance(relative=0.05).contains(0.0, 0.001) is False


class TestPublishedScore:
    def test_percentage_normalises_to_a_fraction(self) -> None:
        score = PublishedScore(
            metric="hit_at_1",
            value=41.16,
            scale=ScoreScale.PERCENTAGE,
            source=SourceReference(kind=SourceKind.PAPER, citation="table 2"),
        )
        assert score.as_fraction() == pytest.approx(0.4116)

    def test_defaults_to_unverified(self) -> None:
        # The default must be the conservative one: a score is unverified until
        # someone records that they read it from the source.
        score = PublishedScore(
            metric="ap",
            value=0.3,
            scale=ScoreScale.FRACTION,
            source=SourceReference(kind=SourceKind.PAPER, citation="x"),
        )
        assert score.verified_against_primary is False


class TestContract:
    def test_unknown_field_is_rejected(self) -> None:
        # extra="forbid": a typo must not silently produce a contract with the
        # real field left unset.
        with pytest.raises(ValidationError):
            synthetic_contract(officialcommit=COMMIT)

    def test_duplicate_seeds_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            synthetic_contract(seed_list=[11, 11, 23])

    def test_contract_hash_ignores_progress_fields(self) -> None:
        # Status, blockers, notes and run cross-references record progress
        # against the contract; changing them must not look like changing the
        # experiment.
        base = synthetic_contract()
        moved_on = synthetic_contract(
            status=BenchmarkStatus.RUNNING,
            notes=["something else"],
            blockers=[Blocker(field="notes", code=BlockerCode.MISSING_FIELD, detail="x")],
        )
        assert base.contract_hash() == moved_on.contract_hash()

    def test_contract_hash_tracks_the_experimental_definition(self) -> None:
        base = synthetic_contract()
        assert base.contract_hash() != synthetic_contract(data_version="2.0.0").contract_hash()

    def test_all_metrics_is_sorted_and_deduplicated(self) -> None:
        contract = synthetic_contract(
            primary_metric="ap",
            secondary_metrics=["ap", "brier"],
            metric_direction={
                "ap": MetricDirection.HIGHER_IS_BETTER,
                "brier": MetricDirection.LOWER_IS_BETTER,
            },
        )
        assert contract.all_metrics() == ["ap", "brier"]

    def test_published_for_finds_a_metric(self) -> None:
        contract = synthetic_contract()
        assert contract.published_for("average_precision") is not None
        assert contract.published_for("nonexistent") is None

    def test_every_required_contract_field_is_present(self) -> None:
        # The field list is the contract with whoever reads the registry; a
        # silent removal would make every existing record incomplete without
        # any file changing.
        required = {
            "benchmark_id",
            "task_name",
            "benchmark_family",
            "paper_title",
            "paper_reference",
            "official_repository",
            "official_commit",
            "official_release_or_tag",
            "official_code_hash",
            "data_name",
            "data_version",
            "data_hash",
            "data_license",
            "redistribution_allowed",
            "target_definition",
            "forecast_horizon",
            "spatial_unit",
            "temporal_unit",
            "training_period",
            "validation_period",
            "calibration_period",
            "test_period",
            "split_hash",
            "primary_metric",
            "secondary_metrics",
            "metric_direction",
            "metric_implementation",
            "metric_code_hash",
            "published_score",
            "reproduction_tolerance",
            "seed_list",
            "minimum_seed_count",
            "confidence_method",
            "paired_test",
            "hardware_requirements",
            "software_environment",
            "software_lock_hash",
            "maximum_training_cost",
            "maximum_inference_cost",
            "control_run_id",
            "challenger_run_ids",
            "status",
            "blockers",
            "notes",
        }
        assert required <= set(type(synthetic_contract()).model_fields)


class TestPlan:
    def test_run_id_is_deterministic_from_immutable_inputs(self) -> None:
        first = synthetic_plan().run_id(11)
        second = synthetic_plan().run_id(11)
        assert first == second

    def test_run_id_changes_with_the_seed(self) -> None:
        plan = synthetic_plan()
        assert plan.run_id(11) != plan.run_id(23)

    def test_run_id_changes_with_the_commit(self) -> None:
        plan = synthetic_plan()
        other = synthetic_plan(official_commit="c" * 40)
        assert plan.run_id(11) != other.run_id(11)

    def test_blocked_plan_must_name_a_blocker(self) -> None:
        with pytest.raises(ValidationError, match="at least one blocker"):
            synthetic_plan(blocked=True, blockers=[])

    def test_environment_hash_covers_hardware_and_software(self) -> None:
        plan = synthetic_plan()
        different = synthetic_plan(hardware=HardwareRequirements(gpu_count=4))
        assert plan.environment_hash() != different.environment_hash()
        also = synthetic_plan(environment=SoftwareEnvironment(container_image="x@sha256:1"))
        assert plan.environment_hash() != also.environment_hash()


class TestRawRunResult:
    def test_rejects_a_run_that_finished_before_it_started(self) -> None:
        with pytest.raises(ValidationError, match="finished before"):
            RawRunResult(
                plan_hash="sha256:x",
                seed=1,
                exit_code=0,
                stdout_hash="sha256:a",
                stderr_hash="sha256:b",
                started_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
                finished_at=datetime(2026, 3, 1, 11, 0, tzinfo=UTC),
                duration_seconds=10.0,
            )

    def test_rejects_a_naive_timestamp(self) -> None:
        with pytest.raises(ValidationError):
            RawRunResult(
                plan_hash="sha256:x",
                seed=1,
                exit_code=0,
                stdout_hash="sha256:a",
                stderr_hash="sha256:b",
                started_at=datetime(2026, 3, 1, 12, 0),  # noqa: DTZ001
                finished_at=datetime(2026, 3, 1, 12, 5, tzinfo=UTC),
                duration_seconds=10.0,
            )


class TestReproductionRun:
    def test_unit_set_hash_is_order_independent(self) -> None:
        forwards = make_run(unit_ids=["a", "b", "c"])
        backwards = make_run(unit_ids=["c", "b", "a"])
        assert forwards.unit_set_hash() == backwards.unit_set_hash()

    def test_a_nonzero_exit_did_not_succeed(self) -> None:
        assert make_run(exit_code=1).succeeded is False
