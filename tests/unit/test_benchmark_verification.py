"""Strict validation: every rule that must refuse a contract.

Each test below corresponds to a way a benchmark claim has historically gone
wrong. The assertion is always that validation *fails*, and that it fails naming
the rule -- a validator that rejects for the wrong reason is only accidentally
correct.
"""

from __future__ import annotations

from fixtures.benchmarks.harness import COMMIT, blocked_contract, make_run, synthetic_contract
from pramaanx.benchmarks.schemas import (
    BenchmarkStatus,
    Blocker,
    BlockerCode,
    MetricDirection,
    Period,
    PublishedScore,
    ScoreScale,
    SourceKind,
    SourceReference,
    Tolerance,
)
from pramaanx.benchmarks.verification import (
    Severity,
    is_immutable_sha,
    is_internal_track,
    is_mutable_reference,
    permitted_status,
    validate_contract,
    verify_source,
)


def rules(contract, runs=()) -> set[str]:
    return {violation.rule for violation in validate_contract(contract, runs).violations}


def error_rules(contract, runs=()) -> set[str]:
    return {
        v.rule for v in validate_contract(contract, runs).violations if v.severity is Severity.ERROR
    }


class TestImmutableSha:
    def test_accepts_a_full_sha1(self) -> None:
        assert is_immutable_sha("a" * 40)

    def test_accepts_a_full_sha256(self) -> None:
        assert is_immutable_sha("a" * 64)

    def test_rejects_a_short_sha(self) -> None:
        # Short SHAs collide as history grows; a contract pinned to one drifts.
        assert not is_immutable_sha("abc1234")

    def test_rejects_a_branch_name(self) -> None:
        assert not is_immutable_sha("main")
        assert is_mutable_reference("main")
        assert is_mutable_reference("MASTER")

    def test_rejects_empty_and_none(self) -> None:
        assert not is_immutable_sha("")
        assert not is_immutable_sha(None)

    def test_rejects_a_tag(self) -> None:
        assert not is_immutable_sha("v1.0.0")


class TestNegativeControls:
    """The refusals the harness exists to make."""

    def test_a_mutable_branch_cannot_substitute_for_a_commit(self) -> None:
        contract = synthetic_contract(official_commit="main")
        assert "official_commit_immutable" in error_rules(contract)

    def test_a_short_sha_cannot_substitute_for_a_commit(self) -> None:
        assert "official_commit_immutable" in error_rules(
            synthetic_contract(official_commit="abc1234")
        )

    def test_a_missing_official_repository_is_rejected(self) -> None:
        assert "official_repository_required" in error_rules(
            synthetic_contract(official_repository=None)
        )

    def test_a_malformed_repository_url_is_rejected(self) -> None:
        assert "official_repository_wellformed" in error_rules(
            synthetic_contract(official_repository="github.com/example/x")
        )

    def test_a_missing_data_hash_is_rejected(self) -> None:
        assert "dataset_pinned" in error_rules(synthetic_contract(data_hash=None))

    def test_a_missing_data_version_is_rejected(self) -> None:
        assert "dataset_pinned" in error_rules(synthetic_contract(data_version=None))

    def test_an_unknown_licence_without_a_blocker_is_rejected(self) -> None:
        assert "licence_known" in error_rules(synthetic_contract(data_license=None))

    def test_an_unknown_licence_with_a_blocker_is_accepted(self) -> None:
        # An acknowledged gap is not a rule violation; it is an honestly
        # incomplete contract.
        contract = synthetic_contract(
            data_license=None,
            status=BenchmarkStatus.BLOCKED_LICENCE,
            blockers=[
                Blocker(
                    field="data_license",
                    code=BlockerCode.LICENCE_UNKNOWN,
                    detail="terms not read",
                )
            ],
        )
        assert "licence_known" not in error_rules(contract)
        assert validate_contract(contract).is_valid

    def test_an_incomplete_split_is_rejected(self) -> None:
        assert "split_complete" in error_rules(synthetic_contract(test_period=Period()))

    def test_a_missing_split_hash_is_rejected(self) -> None:
        assert "split_pinned" in error_rules(synthetic_contract(split_hash=None))

    def test_training_overlapping_test_is_rejected(self) -> None:
        contract = synthetic_contract(training_period=Period(start="2020-01-01", end="2024-06-30"))
        assert "split_disjoint" in error_rules(contract)

    def test_a_primary_metric_without_a_direction_is_rejected(self) -> None:
        contract = synthetic_contract(
            metric_direction={"brier_score": MetricDirection.LOWER_IS_BETTER}
        )
        assert "metric_direction_required" in error_rules(contract)

    def test_a_secondary_metric_without_a_direction_only_warns(self) -> None:
        contract = synthetic_contract(
            secondary_metrics=["brier_score", "novel_metric"],
        )
        report = validate_contract(contract)
        assert any(
            v.rule == "metric_direction_required" and v.severity is Severity.WARNING
            for v in report.violations
        )

    def test_a_published_score_from_a_secondary_source_is_rejected(self) -> None:
        # The rule the whole registry turns on: a number quoted from a design
        # document is not a published score.
        contract = synthetic_contract(
            published_score=[
                PublishedScore(
                    metric="average_precision",
                    value=0.304,
                    scale=ScoreScale.FRACTION,
                    source=SourceReference(kind=SourceKind.INTERNAL, citation="project theory PDF"),
                    verified_against_primary=False,
                )
            ]
        )
        assert "published_score_verified" in error_rules(contract)

    def test_a_published_score_with_an_empty_citation_is_rejected(self) -> None:
        contract = synthetic_contract(
            published_score=[
                PublishedScore(
                    metric="average_precision",
                    value=0.4,
                    scale=ScoreScale.FRACTION,
                    source=SourceReference(kind=SourceKind.PAPER, citation="   "),
                    verified_against_primary=True,
                )
            ]
        )
        assert "published_score_sourced" in error_rules(contract)

    def test_a_missing_tolerance_is_rejected(self) -> None:
        assert "tolerance_required" in error_rules(synthetic_contract(reproduction_tolerance={}))

    def test_a_tolerance_missing_the_primary_metric_is_rejected(self) -> None:
        contract = synthetic_contract(
            reproduction_tolerance={"brier_score": Tolerance(absolute=0.01)}
        )
        assert "tolerance_required" in error_rules(contract)

    def test_an_empty_seed_list_is_rejected(self) -> None:
        assert "seeds_required" in error_rules(synthetic_contract(seed_list=[]))

    def test_too_few_seeds_for_the_declared_minimum_is_rejected(self) -> None:
        assert "seeds_sufficient" in error_rules(
            synthetic_contract(seed_list=[11], minimum_seed_count=5)
        )

    def test_a_missing_confidence_method_is_rejected(self) -> None:
        assert "confidence_method_required" in error_rules(
            synthetic_contract(confidence_method=None)
        )

    def test_a_missing_paired_test_is_rejected(self) -> None:
        assert "paired_test_required" in error_rules(synthetic_contract(paired_test=None))

    def test_a_missing_environment_lock_is_rejected(self) -> None:
        assert "environment_pinned" in error_rules(synthetic_contract(software_lock_hash=None))

    def test_a_missing_cost_budget_is_rejected(self) -> None:
        # Cost cannot be omitted from a comparison, so it cannot be absent from
        # the contract either.
        assert "cost_budget_required" in error_rules(synthetic_contract(maximum_training_cost=None))

    def test_a_blocker_naming_a_field_that_does_not_exist_is_rejected(self) -> None:
        contract = synthetic_contract(
            blockers=[Blocker(field="not_a_field", code=BlockerCode.MISSING_FIELD, detail="typo")]
        )
        assert "blocker_names_real_field" in error_rules(contract)

    def test_a_challenger_cannot_precede_reproduction(self) -> None:
        contract = synthetic_contract(
            challenger_run_ids=["brun_x"],
            control_run_id="brun_c",
            status=BenchmarkStatus.NOT_STARTED,
        )
        assert "challenger_after_reproduction" in error_rules(contract)

    def test_a_challenger_with_no_control_is_rejected(self) -> None:
        contract = synthetic_contract(
            challenger_run_ids=["brun_x"],
            control_run_id=None,
            status=BenchmarkStatus.REPRODUCED,
        )
        assert "challenger_after_reproduction" in error_rules(contract)

    def test_exceeded_without_a_comparison_is_rejected(self) -> None:
        contract = synthetic_contract(
            status=BenchmarkStatus.EXCEEDED,
            control_run_id="brun_c",
            challenger_run_ids=[],
        )
        assert "exceeded_requires_comparison" in error_rules(contract)

    def test_exceeded_without_a_declared_test_is_rejected(self) -> None:
        contract = synthetic_contract(
            status=BenchmarkStatus.EXCEEDED,
            control_run_id="brun_c",
            challenger_run_ids=["brun_x"],
            confidence_method=None,
            paired_test=None,
        )
        assert "exceeded_requires_comparison" in error_rules(contract)

    def test_a_declared_status_stronger_than_the_evidence_is_rejected(self) -> None:
        # "code exists" written up as "reproduced".
        contract = synthetic_contract(status=BenchmarkStatus.REPRODUCED)
        report = validate_contract(contract)
        assert not report.is_valid
        assert report.permitted_status is BenchmarkStatus.NOT_STARTED
        assert "status_supported_by_evidence" in error_rules(contract)


class TestOrderingWithRuns:
    def test_test_period_results_before_opening_are_rejected(self) -> None:
        contract = synthetic_contract()
        run = make_run(contract).model_copy(update={"reads_test_period": True})
        assert "test_period_sealed" in error_rules(contract, [run])

    def test_an_open_test_without_an_authorisation_is_rejected(self) -> None:
        contract = synthetic_contract()
        contract.final_test_policy.opened = True
        assert "test_opening_authorised" in error_rules(contract)

    def test_post_test_changes_invalidate(self) -> None:
        contract = synthetic_contract(control_run_id=None, status=BenchmarkStatus.REPRODUCED)
        run = make_run(contract).model_copy(update={"post_test_changes": ["model:weights"]})
        assert "post_test_change_invalidates" in error_rules(contract, [run])

    def test_a_run_from_a_different_contract_version_is_rejected(self) -> None:
        # Changing the metric code or the environment must not leave old runs
        # silently attached to the new contract.
        contract = synthetic_contract()
        stale = make_run(contract).model_copy(update={"contract_hash": "sha256:" + "0" * 64})
        assert "run_matches_contract" in error_rules(contract, [stale])

    def test_an_unresolvable_run_reference_only_warns(self) -> None:
        contract = synthetic_contract(control_run_id="brun_missing")
        run = make_run(contract)
        report = validate_contract(contract, [run])
        assert any(
            v.rule == "run_reference_resolves" and v.severity is Severity.WARNING
            for v in report.violations
        )


class TestPermittedStatus:
    def test_structural_errors_force_contract_incomplete(self) -> None:
        contract = synthetic_contract(official_repository=None)
        assert validate_contract(contract).permitted_status is (BenchmarkStatus.CONTRACT_INCOMPLETE)

    def test_a_licence_blocker_gives_blocked_licence(self) -> None:
        contract = synthetic_contract(
            data_license=None,
            status=BenchmarkStatus.BLOCKED_LICENCE,
            blockers=[
                Blocker(
                    field="data_license",
                    code=BlockerCode.LICENCE_UNKNOWN,
                    detail="not read",
                )
            ],
        )
        assert validate_contract(contract).permitted_status is BenchmarkStatus.BLOCKED_LICENCE

    def test_a_data_blocker_gives_blocked_data(self) -> None:
        contract = synthetic_contract(
            data_hash=None,
            status=BenchmarkStatus.BLOCKED_DATA,
            blockers=[
                Blocker(
                    field="data_hash",
                    code=BlockerCode.DATA_UNAVAILABLE,
                    detail="not obtained",
                )
            ],
        )
        assert validate_contract(contract).permitted_status is BenchmarkStatus.BLOCKED_DATA

    def test_a_compute_blocker_gives_blocked_environment(self) -> None:
        contract = synthetic_contract(
            status=BenchmarkStatus.BLOCKED_ENVIRONMENT,
            blockers=[
                Blocker(
                    field="hardware_requirements",
                    code=BlockerCode.COMPUTE_UNAVAILABLE,
                    detail="no GPU",
                )
            ],
        )
        assert validate_contract(contract).permitted_status is (BenchmarkStatus.BLOCKED_ENVIRONMENT)

    def test_an_incomplete_field_outranks_an_unobtainable_dataset(self) -> None:
        # "We cannot define this benchmark" is weaker than "we have defined it
        # and cannot download it", so it wins.
        contract = blocked_contract(
            blockers=[
                Blocker(
                    field="data_license",
                    code=BlockerCode.LICENCE_UNKNOWN,
                    detail="not read",
                ),
                Blocker(
                    field="official_commit",
                    code=BlockerCode.MISSING_FIELD,
                    detail="unknown",
                ),
            ],
            official_commit=None,
            status=BenchmarkStatus.CONTRACT_INCOMPLETE,
        )
        assert validate_contract(contract).permitted_status is (BenchmarkStatus.CONTRACT_INCOMPLETE)

    def test_a_reproducing_control_permits_reproduced(self) -> None:
        contract = synthetic_contract()
        run = make_run(contract)
        with_control = synthetic_contract(
            control_run_id=run.run_id, status=BenchmarkStatus.REPRODUCED
        )
        report = validate_contract(with_control, [run])
        assert report.permitted_status is BenchmarkStatus.REPRODUCED
        assert report.is_valid

    def test_a_control_outside_tolerance_is_reproduction_failed(self) -> None:
        contract = synthetic_contract()
        run = make_run(contract, metrics={"average_precision": 0.20, "brier_score": 0.05})
        with_control = synthetic_contract(
            control_run_id=run.run_id, status=BenchmarkStatus.REPRODUCTION_FAILED
        )
        assert validate_contract(with_control, [run]).permitted_status is (
            BenchmarkStatus.REPRODUCTION_FAILED
        )

    def test_a_failed_control_is_reproduction_failed(self) -> None:
        contract = synthetic_contract()
        run = make_run(contract, exit_code=1)
        with_control = synthetic_contract(
            control_run_id=run.run_id, status=BenchmarkStatus.REPRODUCTION_FAILED
        )
        assert validate_contract(with_control, [run]).permitted_status is (
            BenchmarkStatus.REPRODUCTION_FAILED
        )

    def test_permitted_status_is_computed_not_read(self) -> None:
        contract = synthetic_contract(status=BenchmarkStatus.EXCEEDED)
        assert permitted_status(contract, []) is not BenchmarkStatus.EXCEEDED


class TestInternalTrack:
    def test_an_internal_track_needs_no_published_score(self) -> None:
        contract = synthetic_contract(
            paper_title=None,
            paper_reference=SourceReference(kind=SourceKind.INTERNAL, citation="our own track"),
            published_score=[],
        )
        assert is_internal_track(contract)
        assert "published_score_required" not in error_rules(contract)

    def test_an_internal_track_can_never_be_reproduced(self) -> None:
        # There is no published result to have reproduced, so however well the
        # run went, 'reproduced' is not available.
        contract = synthetic_contract(
            paper_title=None,
            paper_reference=SourceReference(kind=SourceKind.INTERNAL, citation="our own track"),
            published_score=[],
        )
        run = make_run(contract)
        with_control = contract.model_copy(update={"control_run_id": run.run_id})
        assert permitted_status(with_control, [], [run]) is BenchmarkStatus.RUNNING


class TestSourceVerification:
    def test_offline_verification_records_that_it_was_offline(self) -> None:
        verification = verify_source(synthetic_contract(), offline=True)
        assert verification.offline
        assert any(check.name == "offline_mode" for check in verification.checks)

    def test_a_complete_contract_verifies(self) -> None:
        assert verify_source(synthetic_contract()).verified

    def test_every_required_source_check_is_present(self) -> None:
        names = {check.name for check in verify_source(synthetic_contract()).checks}
        assert {
            "repository_url",
            "immutable_commit",
            "archive_or_checkout_hash",
            "licence",
            "required_submodules",
            "environment_files",
            "expected_entrypoint",
            "expected_dataset_references",
        } <= names

    def test_a_missing_commit_is_unmet(self) -> None:
        verification = verify_source(synthetic_contract(official_commit=None))
        assert not verification.verified
        assert "immutable_commit" in verification.unmet()

    def test_an_unverified_published_score_is_unmet(self) -> None:
        contract = synthetic_contract(
            published_score=[
                PublishedScore(
                    metric="average_precision",
                    value=0.4,
                    scale=ScoreScale.FRACTION,
                    source=SourceReference(kind=SourceKind.PAPER, citation="table"),
                    verified_against_primary=False,
                )
            ]
        )
        assert "published_score_primary_verified" in verify_source(contract).unmet()

    def test_report_serialises(self) -> None:
        payload = verify_source(synthetic_contract()).to_dict()
        assert payload["verified"] is True
        assert payload["offline"] is True


class TestValidationReport:
    def test_serialises_with_counts(self) -> None:
        payload = validate_contract(synthetic_contract(seed_list=[])).to_dict()
        assert payload["error_count"] >= 1
        assert payload["is_valid"] is False

    def test_a_complete_contract_has_no_errors(self) -> None:
        report = validate_contract(synthetic_contract())
        assert report.errors == []
        assert report.is_valid

    def test_violation_renders_readably(self) -> None:
        report = validate_contract(synthetic_contract(seed_list=[]))
        assert "seeds_required" in str(report.errors[0])

    def test_commit_constant_is_a_valid_sha(self) -> None:
        assert is_immutable_sha(COMMIT)
