"""The source-contract registry, and the alarm that fires when one drifts.

Two things are being defended here. The first is that every connector can say
whether anything it returns has ever been checked against the real service. The
second is that nobody can quietly change that answer: the pinned hashes below
turn an edit to a contract into a failing test, so the change is reviewed rather
than merged as a diff nobody read.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from pramaanx.config import Settings
from pramaanx.ingest.base import available_connectors
from pramaanx.ingest.contracts import (
    SOURCE_CONTRACTS,
    PinnedResource,
    SourceContract,
    UnknownSourceError,
    VerificationState,
    contract_for,
    contract_manifest,
    contract_summaries,
    unverified,
)
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.timeguard.snapshots import SnapshotBuilder

CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)

#: ``source_id -> (contract_version, contract_hash)``.
#:
#: Changing a contract without bumping its version fails the first assertion;
#: bumping the version without updating this table fails the second. Both are
#: meant to. A source contract is a claim about what an external service does
#: and about how thoroughly that claim was checked, and it should not be
#: possible to alter one in a diff that nobody looks at twice.
PINNED_CONTRACTS: dict[str, tuple[str, str]] = {
    "acled": ("1.0.0", "sha256:094283ee1e3c4a1232b9a6b9b123a1036531e0fff42d99914e5265d4e42f4f97"),
    "data_gov_in": (
        "1.0.0",
        "sha256:d6c65cd74cc259e78bac47bb3349468fa230e08878850e6738cd0ef79b9ccfd6",
    ),
    "gdelt": ("1.0.0", "sha256:cf62364b48a796678c936cae9c6796d4ce8f9efeef55dd809b7d3501c778b7fb"),
    "reliefweb": (
        "2.0.0",
        "sha256:3d632d79a0a0e43a5ad7efcb78da7d50ded53a425a9ea35ae448024217622b7e",
    ),
    "synthetic": (
        "1.0.0",
        "sha256:fd5e8b7c9dc932adba3c477bedc55cf6a4ea566fb1959ad11e544c9ddc5abab9",
    ),
}


class TestRegistryCoverage:
    def test_every_registered_connector_declares_a_contract(self) -> None:
        missing = sorted(set(available_connectors()) - set(SOURCE_CONTRACTS))
        assert not missing, (
            f"connectors with no declared contract: {missing}. A connector that cannot "
            "say whether its contract was ever answered by the real service should not "
            "be able to ingest."
        )

    def test_no_contract_outlives_its_connector(self) -> None:
        orphans = sorted(set(SOURCE_CONTRACTS) - set(available_connectors()))
        assert not orphans, (
            f"contracts for connectors that no longer exist: {orphans}. A stale "
            "verification record is worse than none: it answers a question about "
            "code that was deleted."
        )

    def test_contract_key_matches_its_source_id(self) -> None:
        for key, contract in SOURCE_CONTRACTS.items():
            assert key == contract.source_id


class TestDriftAlarm:
    @pytest.mark.parametrize("source_id", sorted(PINNED_CONTRACTS))
    def test_contract_matches_its_pin(self, source_id: str) -> None:
        expected_version, expected_hash = PINNED_CONTRACTS[source_id]
        contract = contract_for(source_id)
        assert contract.contract_version == expected_version, (
            f"{source_id}'s contract version moved to {contract.contract_version}. "
            "Update PINNED_CONTRACTS in the same commit, so the change is reviewed "
            "alongside whatever prompted it."
        )
        assert contract.contract_hash == expected_hash, (
            f"{source_id}'s contract changed but its version stayed at "
            f"{contract.contract_version}. Bump contract_version and update "
            "PINNED_CONTRACTS. An unannounced contract change is how a source "
            "silently stops meaning what a past manifest says it meant."
        )

    def test_the_pin_covers_every_contract(self) -> None:
        assert set(PINNED_CONTRACTS) == set(SOURCE_CONTRACTS), (
            "a contract exists that no pin covers, so it could change unnoticed"
        )


class TestEvidenceMatchesClaim:
    def test_live_claim_without_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="live_evidence"):
            SourceContract(
                source_id="example",
                contract_version="1.0.0",
                state=VerificationState.LIVE_VERIFIED,
                verification_route="tests/network/test_example_live.py",
                live_verified_on=date(2026, 8, 27),
                live_verification_scope="one request",
            )

    def test_unverified_source_must_name_its_blocker(self) -> None:
        with pytest.raises(ValidationError, match="names no blocker"):
            SourceContract(
                source_id="example",
                contract_version="1.0.0",
                state=VerificationState.DOCS_ONLY,
                verification_route="tests/network/test_example_live.py",
                docs_verified_on=date(2026, 8, 26),
            )

    def test_downgrade_must_drop_stale_live_detail(self) -> None:
        with pytest.raises(ValidationError, match="carries live-verification detail"):
            SourceContract(
                source_id="example",
                contract_version="1.0.0",
                state=VerificationState.DOCS_ONLY,
                verification_route="tests/network/test_example_live.py",
                docs_verified_on=date(2026, 8, 26),
                blocker="credential expired",
                live_verified_on=date(2026, 1, 1),
            )

    def test_live_and_blocked_cannot_both_be_true(self) -> None:
        with pytest.raises(ValidationError, match="stale"):
            SourceContract(
                source_id="example",
                contract_version="1.0.0",
                state=VerificationState.LIVE_VERIFIED,
                verification_route="tests/network/test_example_live.py",
                live_verified_on=date(2026, 8, 27),
                live_verification_scope="one request",
                live_evidence="run 1",
                blocker="waiting on a credential",
            )

    def test_docs_verified_source_is_not_unverified(self) -> None:
        with pytest.raises(ValidationError, match="docs_only, not unverified"):
            SourceContract(
                source_id="example",
                contract_version="1.0.0",
                state=VerificationState.UNVERIFIED,
                verification_route="tests/network/test_example_live.py",
                docs_verified_on=date(2026, 8, 26),
                blocker="nobody has run it",
            )


class TestPinnedResource:
    def test_a_schema_pin_needs_a_capture_date(self) -> None:
        with pytest.raises(ValidationError, match="copied out of a fixture"):
            PinnedResource(
                resource_id="abc",
                title="Example",
                pinned_on=date(2026, 8, 27),
                field_names=("a", "b"),
            )

    def test_drift_refuses_to_guess_without_a_captured_schema(self) -> None:
        resource = PinnedResource(resource_id="abc", title="Example", pinned_on=date(2026, 8, 27))
        assert not resource.schema_pinned
        with pytest.raises(ValueError, match="no captured schema"):
            resource.drift_against({"a"})

    def test_drift_reports_both_directions(self) -> None:
        resource = PinnedResource(
            resource_id="abc",
            title="Example",
            pinned_on=date(2026, 8, 27),
            field_names=("a", "b"),
            schema_captured_on=date(2026, 8, 27),
        )
        vanished, appeared = resource.drift_against({"b", "c"})
        assert vanished == {"a"}
        assert appeared == {"c"}

    def test_the_data_gov_in_resource_is_pinned_by_identifier(self) -> None:
        (resource,) = contract_for("data_gov_in").pinned_resources
        assert resource.resource_id == "869c674d-59a4-4de3-8b09-f2b709983f51"
        # Not yet captured: the 2026-08-27 live run recorded the envelope
        # contract, not the record field names, and the only data.gov.in
        # records in this repository are openly synthetic.
        assert not resource.schema_pinned


class TestLookupAndSummaries:
    def test_unknown_source_names_what_is_registered(self) -> None:
        with pytest.raises(UnknownSourceError, match="reliefweb"):
            contract_for("no_such_source")

    def test_summaries_are_sorted_and_compact(self) -> None:
        assert contract_summaries(["reliefweb", "gdelt"]) == {
            "gdelt": "gdelt@1.0.0/live_verified",
            "reliefweb": "reliefweb@2.0.0/docs_only",
        }

    def test_manifest_entry_carries_evidence_or_blocker(self) -> None:
        entries = contract_manifest(["gdelt", "acled"])
        assert entries["gdelt"]["state"] == "live_verified"
        assert "actions/runs/" in entries["gdelt"]["live_evidence"]
        assert "myACLED" in entries["acled"]["blocker"]
        assert "live_evidence" not in entries["acled"]

    def test_unverified_surfaces_the_two_blocked_sources_first(self) -> None:
        blocked = [contract.source_id for contract in unverified()]
        assert blocked == ["acled", "reliefweb", "synthetic"]

    def test_the_live_verified_sources_are_gdelt_and_data_gov_in(self) -> None:
        live = sorted(
            source_id for source_id, contract in SOURCE_CONTRACTS.items() if contract.live_verified
        )
        assert live == ["data_gov_in", "gdelt"]


class TestManifestIntegration:
    def test_snapshot_manifest_records_the_contract(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        manifest = SnapshotBuilder(settings, populated_ledger).build(CUTOFF).manifest
        assert manifest.source_contracts == {"synthetic": "synthetic@1.0.0/synthetic"}

    def test_verification_status_does_not_move_the_snapshot_hash(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        """Learning something about a source does not rewrite last month's evidence.

        This is the deliberate exclusion documented on ``content_fingerprint``.
        If it ever stops holding, every historical snapshot becomes
        un-reproducible the day a credential finally arrives.
        """
        snapshot = SnapshotBuilder(settings, populated_ledger).build(CUTOFF, persist=False)
        before = snapshot.manifest.snapshot_hash

        snapshot.manifest.source_contracts = {"synthetic": "synthetic@9.9.9/live_verified"}

        assert snapshot.manifest.snapshot_hash == before
