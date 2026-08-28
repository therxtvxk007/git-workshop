"""The committed registry is a contract with whoever reads it.

These tests run against the real ``research/benchmarks`` files, not a fixture.
They assert that every record in the repository is internally consistent, that
its declared status is one its evidence supports, and -- most importantly -- that
nothing in it claims to have reproduced anything.

That last assertion is the one to keep. WP-B0 builds the referee; if a future
change lets a contract reach ``reproduced`` without a run behind it, this file
should be what fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner, Result

from fixtures.benchmarks.harness import make_run, paired_unit_scores, synthetic_contract
from pramaanx.benchmarks.__main__ import app as benchmarks_app
from pramaanx.benchmarks.manifests import ManifestStore
from pramaanx.benchmarks.registry import (
    DEFAULT_CONTRACT_DIR,
    DEFAULT_REGISTRY_PATH,
    REGISTRY_VERSION,
    RegistryError,
    RegistryFileExistsError,
    dump_contract,
    dump_registry_index,
    load_contract,
    load_registry,
    registry_manifest,
    write_contract,
)
from pramaanx.benchmarks.schemas import BenchmarkStatus, ScoreScale
from pramaanx.benchmarks.verification import is_immutable_sha, validate_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / DEFAULT_REGISTRY_PATH
CONTRACT_DIR = REPO_ROOT / DEFAULT_CONTRACT_DIR
RUNS_DIR = REPO_ROOT / "research" / "benchmarks" / "reproductions"

REGISTRY = load_registry(REGISTRY_PATH)
CONTRACTS = list(REGISTRY)
IDS = [contract.benchmark_id for contract in CONTRACTS]

REQUIRED_FAMILIES = {
    "hydranet_views",
    "views_challenge",
    "stk_adapter",
    "dymrl",
    "memotime",
    "conformal",
    "pramaanx_india",
}


class TestRegistryLoads:
    def test_the_registry_file_exists(self) -> None:
        assert REGISTRY_PATH.exists()

    def test_declares_the_expected_version(self) -> None:
        assert REGISTRY.version == REGISTRY_VERSION

    def test_every_referenced_contract_file_exists(self) -> None:
        document = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        for entry in document["benchmarks"]:
            assert (CONTRACT_DIR / entry["contract"]).exists(), entry["contract"]

    def test_no_contract_file_is_orphaned(self) -> None:
        # A contract file the index does not point at would silently vanish from
        # every report.
        on_disk = {path.name for path in CONTRACT_DIR.glob("*.yaml")}
        document = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        referenced = {entry["contract"] for entry in document["benchmarks"]}
        assert on_disk == referenced

    def test_benchmark_ids_are_unique(self) -> None:
        assert len(IDS) == len(set(IDS))

    def test_the_index_status_matches_each_contract(self) -> None:
        document = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        by_id = {entry["benchmark_id"]: entry for entry in document["benchmarks"]}
        for contract in CONTRACTS:
            assert by_id[contract.benchmark_id]["status"] == contract.status.value


class TestRequiredCoverage:
    def test_all_three_hydranet_violence_types_are_registered(self) -> None:
        assert {
            "hydranet_views_state_based",
            "hydranet_views_non_state",
            "hydranet_views_one_sided",
        } <= set(IDS)

    def test_the_views_fatality_challenge_is_registered(self) -> None:
        assert "views_fatality_distribution" in IDS

    def test_all_four_stk_adapter_datasets_are_registered(self) -> None:
        assert {
            "stk_adapter_ice14",
            "stk_adapter_ice15",
            "stk_adapter_ice18",
            "stk_adapter_wiki",
        } <= set(IDS)

    def test_dymrl_memotime_and_conformal_are_registered(self) -> None:
        assert {
            "dymrl_multimodal_tkg",
            "memotime_temporal_reasoning",
            "cptc_conformal",
            "distribution_aware_conformal",
        } <= set(IDS)

    def test_the_india_track_is_registered(self) -> None:
        assert "india_district_30d" in IDS

    def test_every_required_family_is_present(self) -> None:
        assert {contract.benchmark_family for contract in CONTRACTS} >= REQUIRED_FAMILIES


class TestEveryContractIsHonest:
    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_validates(self, contract) -> None:
        report = validate_contract(contract)
        assert report.is_valid, [str(violation) for violation in report.errors]

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_declared_status_matches_the_permitted_status(self, contract) -> None:
        report = validate_contract(contract)
        assert report.declared_status is report.permitted_status

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_nothing_claims_to_be_reproduced_or_exceeded(self, contract) -> None:
        # WP-B0 builds the harness. No reproduction has been run, so no record
        # may say one has.
        assert contract.status not in {
            BenchmarkStatus.REPRODUCED,
            BenchmarkStatus.CHALLENGED_NOT_EXCEEDED,
            BenchmarkStatus.EXCEEDED,
        }

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_no_challenger_runs_are_recorded(self, contract) -> None:
        assert contract.challenger_run_ids == []
        assert contract.control_run_id is None

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_no_final_test_has_been_opened(self, contract) -> None:
        assert contract.final_test_policy.opened is False

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_every_unset_required_field_carries_a_blocker(self, contract) -> None:
        blocked = contract.blocker_fields()
        for field in ("official_commit", "data_hash", "data_version", "split_hash"):
            if getattr(contract, field) is None:
                assert field in blocked, f"{contract.benchmark_id}: {field} unset, unblocked"

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_any_commit_present_is_an_immutable_sha(self, contract) -> None:
        if contract.official_commit is not None:
            assert is_immutable_sha(contract.official_commit)

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_no_published_score_is_marked_verified(self, contract) -> None:
        # arxiv.org, aclanthology.org and journals.sagepub.com were all refused
        # by the egress proxy, so no paper table was read. Any score here
        # claiming primary verification would be false.
        for score in contract.published_score:
            assert not score.verified_against_primary, (
                f"{contract.benchmark_id}/{score.metric} claims primary verification"
            )

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_every_published_score_records_its_scale(self, contract) -> None:
        for score in contract.published_score:
            assert score.scale in set(ScoreScale)
            assert score.verification_note

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_every_blocker_names_a_real_field(self, contract) -> None:
        fields = set(type(contract).model_fields)
        for blocker in contract.blockers:
            assert blocker.field in fields, blocker.field

    @pytest.mark.parametrize("contract", CONTRACTS, ids=IDS)
    def test_seeds_meet_the_declared_minimum(self, contract) -> None:
        assert contract.minimum_seed_count is not None
        assert len(contract.seed_list) >= contract.minimum_seed_count


class TestHydraNetGates:
    """The published values are recorded as claims, and marked as such."""

    GATES = {
        "hydranet_views_state_based": {
            "average_precision": 0.304,
            "roc_auc": 0.921,
            "brier_score": 0.0046,
            "mse": 0.004,
        },
        "hydranet_views_non_state": {
            "average_precision": 0.134,
            "roc_auc": 0.929,
            "brier_score": 0.0020,
            "mse": 0.002,
        },
        "hydranet_views_one_sided": {
            "average_precision": 0.162,
            "roc_auc": 0.900,
            "brier_score": 0.003,
            "mse": 0.003,
        },
    }

    @pytest.mark.parametrize("benchmark_id", sorted(GATES))
    def test_the_gate_values_are_recorded(self, benchmark_id: str) -> None:
        contract = REGISTRY.get(benchmark_id)
        recorded = {score.metric: score.value for score in contract.published_score}
        assert recorded == self.GATES[benchmark_id]

    @pytest.mark.parametrize("benchmark_id", sorted(GATES))
    def test_none_of_them_is_treated_as_verified(self, benchmark_id: str) -> None:
        contract = REGISTRY.get(benchmark_id)
        assert contract.status is BenchmarkStatus.CONTRACT_INCOMPLETE
        assert "published_score" in contract.blocker_fields()

    def test_the_one_sided_discrepancy_is_recorded(self) -> None:
        # A secondary summary reports 0.138 where the brief says 0.162. The
        # conflict is written down rather than resolved by picking one.
        contract = REGISTRY.get("hydranet_views_one_sided")
        assert any("0.138" in note for note in contract.notes)


class TestStkGates:
    GATES = {
        "stk_adapter_ice14": (41.16, 59.03, 70.73),
        "stk_adapter_ice18": (26.88, 45.91, 59.42),
        "stk_adapter_ice15": (48.82, 65.83, 78.22),
        "stk_adapter_wiki": (84.38, 87.22, 88.53),
    }

    @pytest.mark.parametrize("benchmark_id", sorted(GATES))
    def test_the_gate_values_are_recorded(self, benchmark_id: str) -> None:
        contract = REGISTRY.get(benchmark_id)
        recorded = {score.metric: score.value for score in contract.published_score}
        expected = self.GATES[benchmark_id]
        assert recorded == {
            "hit_at_1": expected[0],
            "hit_at_3": expected[1],
            "hit_at_10": expected[2],
        }

    @pytest.mark.parametrize("benchmark_id", sorted(GATES))
    def test_the_reporting_scale_is_recorded(self, benchmark_id: str) -> None:
        # The brief asks explicitly whether the paper reports percentages or
        # fractions, and every score has to say which it assumes.
        for score in REGISTRY.get(benchmark_id).published_score:
            assert score.scale is ScoreScale.PERCENTAGE
            assert "percentage" in (score.verification_note or "")

    @pytest.mark.parametrize("benchmark_id", sorted(GATES))
    def test_the_missing_official_repository_is_blocked(self, benchmark_id: str) -> None:
        contract = REGISTRY.get(benchmark_id)
        assert contract.official_repository is None
        assert "official_repository" in contract.blocker_fields()


class TestIndiaContract:
    CONTRACT = REGISTRY.get("india_district_30d")

    def test_unit_horizon_and_targets(self) -> None:
        assert self.CONTRACT.spatial_unit.startswith("district")
        assert self.CONTRACT.temporal_unit == "monthly cutoff"
        assert self.CONTRACT.forecast_horizon == "30 days from the monthly cutoff"
        assert "occurrence" in self.CONTRACT.target_definition
        assert "count" in self.CONTRACT.target_definition

    def test_event_families(self) -> None:
        for family in ("terrorism", "left-wing extremism", "insurgency"):
            assert family in self.CONTRACT.target_definition

    def test_primary_metric_is_average_precision(self) -> None:
        assert self.CONTRACT.primary_metric == "average_precision"

    def test_every_required_secondary_metric_is_declared(self) -> None:
        assert {
            "brier_score",
            "log_loss",
            "roc_auc",
            "recall_at_5",
            "recall_at_10",
            "recall_at_20",
            "count_deviance",
            "crps",
            "calibration_error",
            "interval_coverage",
            "interval_width",
            "selective_risk",
            "analyst_load",
        } == set(self.CONTRACT.secondary_metrics)

    def test_every_metric_has_a_direction(self) -> None:
        for metric in self.CONTRACT.all_metrics():
            assert self.CONTRACT.direction_of(metric) is not None, metric

    def test_all_four_windows_are_present_and_blocked(self) -> None:
        # Expanding training, model selection, calibration and a frozen final
        # test: four windows, all awaiting a completeness measurement.
        blocked = self.CONTRACT.blocker_fields()
        for field in ("training_period", "validation_period", "calibration_period", "test_period"):
            assert getattr(self.CONTRACT, field) is None
            assert field in blocked

    def test_the_dates_were_not_invented(self) -> None:
        from pramaanx.benchmarks.schemas import BlockerCode

        awaiting = {
            blocker.field
            for blocker in self.CONTRACT.blockers
            if blocker.code is BlockerCode.AWAITING_MEASUREMENT
        }
        assert {"training_period", "test_period"} <= awaiting

    def test_the_reporting_delay_rule_is_stated(self) -> None:
        assert any("reporting delay" in note.lower() for note in self.CONTRACT.notes)

    def test_the_historical_district_universe_is_stated(self) -> None:
        assert any("district universe" in note.lower() for note in self.CONTRACT.notes)

    def test_the_expanding_window_is_stated(self) -> None:
        assert any("expanding window" in note.lower() for note in self.CONTRACT.notes)

    def test_the_final_test_access_policy_is_stated(self) -> None:
        policy = self.CONTRACT.final_test_policy
        assert policy.opened is False
        assert policy.max_openings == 1
        assert policy.requires_frozen_contract
        assert policy.requires_frozen_artefacts
        assert policy.requires_frozen_configs
        assert "opened exactly" in (policy.description or "")

    def test_acled_redistribution_is_refused(self) -> None:
        assert self.CONTRACT.redistribution_allowed is False


class TestRegistryApi:
    def test_lookup_by_id(self) -> None:
        assert REGISTRY.get(IDS[0]).benchmark_id == IDS[0]

    def test_an_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError, match="known ids"):
            REGISTRY.get("nonexistent_benchmark")

    def test_by_status_and_by_family(self) -> None:
        assert REGISTRY.by_status(BenchmarkStatus.CONTRACT_INCOMPLETE)
        assert len(REGISTRY.by_family("stk_adapter")) == 4

    def test_registry_hash_is_stable(self) -> None:
        assert REGISTRY.registry_hash() == load_registry(REGISTRY_PATH).registry_hash()

    def test_len_and_iteration_are_sorted(self) -> None:
        assert len(REGISTRY) == len(IDS)
        assert sorted(IDS) == IDS

    def test_manifest_summarises_by_status(self) -> None:
        manifest = registry_manifest(REGISTRY)
        assert manifest["count"] == len(REGISTRY)
        assert manifest["by_status"]["contract_incomplete"] == len(REGISTRY)


class TestRegistryLoaderRefusals:
    def test_a_missing_registry_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="not found"):
            load_registry(tmp_path / "absent.yaml")

    def test_a_wrong_version_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text(yaml.safe_dump({"version": 99, "benchmarks": []}), encoding="utf-8")
        with pytest.raises(RegistryError, match="version"):
            load_registry(path)

    def test_a_non_mapping_document_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(RegistryError, match="mapping"):
            load_registry(path)

    def test_an_entry_without_a_contract_reference_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text(
            yaml.safe_dump({"version": 1, "benchmarks": [{"benchmark_id": "x"}]}),
            encoding="utf-8",
        )
        with pytest.raises(RegistryError, match="contract"):
            load_registry(path)

    def test_a_mismatched_id_is_refused(self, tmp_path: Path) -> None:
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        (contracts / "one.yaml").write_text(dump_contract(REGISTRY.get(IDS[0])), encoding="utf-8")
        path = tmp_path / "registry.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "benchmarks": [{"benchmark_id": "wrong", "contract": "one.yaml"}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(RegistryError, match="but"):
            load_registry(path)

    def test_a_duplicate_id_is_refused(self, tmp_path: Path) -> None:
        contracts = tmp_path / "contracts"
        contracts.mkdir()
        text = dump_contract(REGISTRY.get(IDS[0]))
        (contracts / "one.yaml").write_text(text, encoding="utf-8")
        (contracts / "two.yaml").write_text(text, encoding="utf-8")
        path = tmp_path / "registry.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "benchmarks": [{"contract": "one.yaml"}, {"contract": "two.yaml"}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(RegistryError, match="duplicate"):
            load_registry(path)

    def test_an_unknown_field_in_a_contract_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        document = yaml.safe_load(dump_contract(REGISTRY.get(IDS[0])))
        document["not_a_real_field"] = 1
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        with pytest.raises(RegistryError):
            load_contract(path)

    def test_a_missing_contract_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="not found"):
            load_contract(tmp_path / "absent.yaml")


class TestRegistryWriting:
    def test_refuses_to_overwrite_an_existing_contract(self, tmp_path: Path) -> None:
        contract = REGISTRY.get(IDS[0])
        path = tmp_path / "c.yaml"
        write_contract(contract, path)
        with pytest.raises(RegistryFileExistsError, match="refusing to overwrite"):
            write_contract(contract, path)

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        write_contract(REGISTRY.get(IDS[0]), path, dry_run=True)
        assert not path.exists()

    def test_an_explicit_overwrite_is_permitted(self, tmp_path: Path) -> None:
        contract = REGISTRY.get(IDS[0])
        path = tmp_path / "c.yaml"
        write_contract(contract, path)
        write_contract(contract, path, overwrite=True)
        assert load_contract(path).benchmark_id == contract.benchmark_id

    def test_a_round_trip_preserves_the_contract_hash(self, tmp_path: Path) -> None:
        for contract in CONTRACTS:
            path = tmp_path / f"{contract.benchmark_id}.yaml"
            write_contract(contract, path)
            assert load_contract(path).contract_hash() == contract.contract_hash()

    def test_the_committed_index_matches_a_regenerated_one(self) -> None:
        assert dump_registry_index(CONTRACTS) == REGISTRY_PATH.read_text(encoding="utf-8")

    def test_the_committed_contracts_are_canonically_serialised(self) -> None:
        # Re-serialising an unchanged contract must be byte-identical, or every
        # diff carries formatting noise.
        for contract in CONTRACTS:
            path = CONTRACT_DIR / f"{contract.benchmark_id}.yaml"
            assert dump_contract(contract) == path.read_text(encoding="utf-8")


class TestCommandSurfaceInProcess:
    """The eight commands, exercised in-process so their lines are measured.

    Typer's CliRunner invokes the same callbacks the module entry point does, so
    these assert real behaviour rather than a wrapper. The subprocess tests below
    prove the ``python -m`` entry point itself works; they are not measured, and
    are not meant to be.
    """

    def invoke(self, *args: str) -> Result:
        return CliRunner().invoke(benchmarks_app, list(args))

    def test_list_renders_every_benchmark(self) -> None:
        result = self.invoke("list", "--registry", str(REGISTRY_PATH))
        assert result.exit_code == 0
        for benchmark_id in IDS:
            assert benchmark_id in result.stdout

    def test_list_json_is_canonical_and_repeatable(self) -> None:
        first = self.invoke("list", "--registry", str(REGISTRY_PATH), "--json")
        second = self.invoke("list", "--registry", str(REGISTRY_PATH), "--json")
        assert first.exit_code == 0
        assert first.stdout == second.stdout
        assert json.loads(first.stdout)["count"] == len(REGISTRY)

    def test_list_filters_by_status(self) -> None:
        result = self.invoke(
            "list", "--registry", str(REGISTRY_PATH), "--status", "reproduced", "--json"
        )
        assert json.loads(result.stdout)["count"] == 0

    def test_an_unknown_status_is_a_usage_error(self) -> None:
        result = self.invoke("list", "--registry", str(REGISTRY_PATH), "--status", "nope")
        assert result.exit_code == 1

    def test_a_missing_registry_is_a_usage_error(self, tmp_path: Path) -> None:
        result = self.invoke("list", "--registry", str(tmp_path / "absent.yaml"))
        assert result.exit_code == 1

    def test_validate_passes_and_reports_each_contract(self) -> None:
        result = self.invoke("validate", "--registry", str(REGISTRY_PATH), "--runs", str(RUNS_DIR))
        assert result.exit_code == 0
        assert "0 failing validation" in result.stdout

    def test_validate_json_lists_no_invalid_contracts(self) -> None:
        result = self.invoke(
            "validate", "--registry", str(REGISTRY_PATH), "--runs", str(RUNS_DIR), "--json"
        )
        assert json.loads(result.stdout)["invalid"] == []

    def test_show_renders_contract_blockers_and_cost(self) -> None:
        result = self.invoke("show", "cptc_conformal", "--registry", str(REGISTRY_PATH))
        assert result.exit_code == 0
        assert "blockers" in result.stdout
        assert "total cost" in result.stdout

    def test_show_json_round_trips(self) -> None:
        result = self.invoke(
            "show", "india_district_30d", "--registry", str(REGISTRY_PATH), "--json"
        )
        assert json.loads(result.stdout)["benchmark_id"] == "india_district_30d"

    def test_verify_source_exits_blocked_with_unmet_checks(self) -> None:
        result = self.invoke("verify-source", "stk_adapter_ice14", "--registry", str(REGISTRY_PATH))
        assert result.exit_code == 3
        assert "unmet" in result.stdout

    def test_plan_exits_blocked_and_names_the_blockers(self) -> None:
        result = self.invoke(
            "plan", "memotime_temporal_reasoning", "--registry", str(REGISTRY_PATH)
        )
        assert result.exit_code == 3
        assert "BLOCKED" in result.stdout

    def test_plan_json_carries_the_plan_hash(self) -> None:
        result = self.invoke("plan", "cptc_conformal", "--registry", str(REGISTRY_PATH), "--json")
        payload = json.loads(result.stdout)
        assert payload["blocked"] is True
        assert payload["plan_hash"].startswith("sha256:")

    def test_reproduce_dry_run_refuses_and_writes_nothing(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        result = self.invoke(
            "reproduce",
            "cptc_conformal",
            "--registry",
            str(REGISTRY_PATH),
            "--runs",
            str(runs),
            "--dry-run",
        )
        assert result.exit_code == 3
        assert "REFUSED" in result.stdout
        assert not runs.exists()

    def test_reproduce_with_execute_still_refuses_a_blocked_benchmark(self, tmp_path: Path) -> None:
        result = self.invoke(
            "reproduce",
            "cptc_conformal",
            "--registry",
            str(REGISTRY_PATH),
            "--runs",
            str(tmp_path),
            "--execute",
        )
        assert result.exit_code == 3

    def test_report_renders_a_benchmark(self) -> None:
        result = self.invoke(
            "report",
            "hydranet_views_one_sided",
            "--registry",
            str(REGISTRY_PATH),
            "--runs",
            str(RUNS_DIR),
        )
        assert result.exit_code == 0
        assert "0.138" in result.stdout  # the recorded discrepancy note

    def test_compare_refuses_when_a_run_manifest_is_missing(self, tmp_path: Path) -> None:
        result = self.invoke(
            "compare",
            "cptc_conformal",
            "--registry",
            str(REGISTRY_PATH),
            "--runs",
            str(tmp_path),
            "--control-run",
            "brun_absent",
            "--challenger-run",
            "brun_also_absent",
        )
        assert result.exit_code == 1

    def test_output_refuses_to_overwrite(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        target.write_text("existing", encoding="utf-8")
        result = self.invoke("list", "--registry", str(REGISTRY_PATH), "--json", "-o", str(target))
        assert result.exit_code == 1
        assert target.read_text(encoding="utf-8") == "existing"

    def test_output_writes_canonical_json_when_absent(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "out.json"
        result = self.invoke("list", "--registry", str(REGISTRY_PATH), "--json", "-o", str(target))
        assert result.exit_code == 0
        assert json.loads(target.read_text(encoding="utf-8"))["count"] == len(REGISTRY)


class TestCompareEndToEnd:
    """`compare` over real manifests, through the CLI, on a synthetic contract.

    The contract used here is the fixture, not a registered benchmark: nothing in
    `research/benchmarks/` has a control run, and manufacturing one would be the
    exact false claim this package exists to prevent.
    """

    def write_registry(self, tmp_path: Path, contract) -> Path:
        contracts = tmp_path / "contracts"
        contracts.mkdir(parents=True, exist_ok=True)
        write_contract(contract, contracts / f"{contract.benchmark_id}.yaml")
        registry = tmp_path / "registry.yaml"
        registry.write_text(dump_registry_index([contract]), encoding="utf-8")
        return registry

    def setup_runs(self, tmp_path: Path):
        contract = synthetic_contract()
        control_units, challenger_units = paired_unit_scores(count=40, lift=0.03)
        control = make_run(
            contract,
            seed=11,
            metrics={"average_precision": 0.402, "brier_score": 0.049},
            per_unit={"average_precision": control_units},
        )
        challengers = [
            make_run(
                contract,
                seed=seed,
                metrics={"average_precision": 0.432, "brier_score": 0.048},
                per_unit={"average_precision": challenger_units},
                role="challenger",
            )
            for seed in (23, 37, 53)
        ]
        runs = tmp_path / "runs"
        store = ManifestStore(runs)
        for run in (control, *challengers):
            store.write(run)
        return self.write_registry(tmp_path, contract), runs, control, challengers

    def test_a_genuine_improvement_is_reported_as_exceeded(self, tmp_path: Path) -> None:
        registry, runs, control, challengers = self.setup_runs(tmp_path)
        result = CliRunner().invoke(
            benchmarks_app,
            [
                "compare",
                "synthetic_fixture",
                "--registry",
                str(registry),
                "--runs",
                str(runs),
                "--control-run",
                control.run_id,
                *[arg for run in challengers for arg in ("--challenger-run", run.run_id)],
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "exceeded" in result.stdout

    def test_a_refusal_exits_non_zero_and_names_the_gate(self, tmp_path: Path) -> None:
        registry, runs, control, challengers = self.setup_runs(tmp_path)
        result = CliRunner().invoke(
            benchmarks_app,
            [
                "compare",
                "synthetic_fixture",
                "--registry",
                str(registry),
                "--runs",
                str(runs),
                "--control-run",
                control.run_id,
                "--challenger-run",
                challengers[0].run_id,
            ],
        )
        # One seed against a minimum of three.
        assert result.exit_code == 2
        assert "FAIL  minimum_seeds" in result.stdout

    def test_report_includes_every_run(self, tmp_path: Path) -> None:
        registry, runs, _, _ = self.setup_runs(tmp_path)
        result = CliRunner().invoke(
            benchmarks_app,
            [
                "report",
                "synthetic_fixture",
                "--registry",
                str(registry),
                "--runs",
                str(runs),
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["run_counts"]["total"] == 4

    def test_a_malformed_comparison_is_refused(self, tmp_path: Path) -> None:
        contract = synthetic_contract(primary_metric=None)
        registry = self.write_registry(tmp_path, contract)
        runs = tmp_path / "runs"
        run = make_run(synthetic_contract())
        ManifestStore(runs).write(run)
        result = CliRunner().invoke(
            benchmarks_app,
            [
                "compare",
                "synthetic_fixture",
                "--registry",
                str(registry),
                "--runs",
                str(runs),
                "--control-run",
                run.run_id,
                "--challenger-run",
                run.run_id,
            ],
        )
        assert result.exit_code == 2


class TestCommandSurface:
    """``python -m pramaanx.benchmarks`` exists and behaves."""

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pramaanx.benchmarks", *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )

    def test_every_declared_command_is_present(self) -> None:
        result = self.run_cli("--help")
        assert result.returncode == 0
        for command in (
            "list",
            "validate",
            "show",
            "verify-source",
            "plan",
            "reproduce",
            "compare",
            "report",
        ):
            assert command in result.stdout

    def test_list_emits_deterministic_json(self) -> None:
        first = self.run_cli("list", "--json")
        second = self.run_cli("list", "--json")
        assert first.returncode == 0
        assert first.stdout == second.stdout

    def test_validate_passes_on_the_committed_registry(self) -> None:
        result = self.run_cli("validate")
        assert result.returncode == 0, result.stdout

    def test_show_renders_a_benchmark(self) -> None:
        result = self.run_cli("show", "india_district_30d")
        assert result.returncode == 0
        assert "india_district_30d" in result.stdout

    def test_an_unknown_benchmark_exits_with_a_usage_error(self) -> None:
        result = self.run_cli("show", "nope")
        assert result.returncode == 1

    def test_plan_reports_a_blocked_benchmark_with_a_blocked_exit(self) -> None:
        result = self.run_cli("plan", "cptc_conformal")
        assert result.returncode == 3
        assert "BLOCKED" in result.stdout

    def test_reproduce_defaults_to_a_dry_run_and_refuses(self) -> None:
        result = self.run_cli("reproduce", "cptc_conformal")
        assert result.returncode == 3
        assert "REFUSED" in result.stdout

    def test_verify_source_is_offline_and_reports_unmet_checks(self) -> None:
        result = self.run_cli("verify-source", "hydranet_views_state_based", "--json")
        assert result.returncode == 3
        assert '"offline":true' in result.stdout

    def test_no_shared_top_level_command_is_registered(self) -> None:
        # WP-B0 must not claim a subcommand on the main CLI; a later integration
        # package can mount it.
        from pramaanx.cli._app import app

        names = {command.name for command in app.registered_commands}
        groups = {group.name for group in app.registered_groups}
        assert "benchmarks" not in names | groups


class TestBenchmarkConfig:
    """`configs/benchmarks/` is its own config family and needs its own contract.

    It is excluded from the pipeline-config sweeps in
    `tests/contracts/test_config_contracts.py` because it is not a `Settings`
    document. Excluded is not the same as unchecked, so it is checked here.
    """

    PATH = REPO_ROOT / "configs" / "benchmarks" / "default.yaml"
    DOCUMENT = yaml.safe_load(PATH.read_text(encoding="utf-8"))

    def test_exists_and_is_a_mapping(self) -> None:
        assert isinstance(self.DOCUMENT, dict)
        assert self.DOCUMENT["version"] == REGISTRY_VERSION

    def test_the_paths_it_names_exist(self) -> None:
        for key in ("registry", "contracts", "reproductions"):
            assert (REPO_ROOT / self.DOCUMENT[key]).exists(), key

    def test_it_points_at_the_registry_this_test_loaded(self) -> None:
        assert REPO_ROOT / self.DOCUMENT["registry"] == REGISTRY_PATH

    def test_dry_run_is_the_default(self) -> None:
        # Running a third party's benchmark code is an explicit act.
        assert self.DOCUMENT["defaults"]["dry_run"] is True

    def test_the_third_party_cache_is_git_ignored(self) -> None:
        # Official repositories are never vendored into this repository, and
        # several registered datasets forbid redistribution outright.
        cache = self.DOCUMENT["third_party_cache"]
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert cache.startswith(".cache/")
        assert ".cache/" in ignored

    def test_the_declared_protocol_matches_every_contract(self) -> None:
        protocol = self.DOCUMENT["protocol"]
        for contract in CONTRACTS:
            assert contract.seed_list == protocol["seed_list"]
            assert contract.minimum_seed_count == protocol["minimum_seed_count"]

    def test_no_third_party_repository_is_vendored(self) -> None:
        cache = REPO_ROOT / self.DOCUMENT["third_party_cache"]
        assert not cache.exists() or not any(cache.iterdir())
