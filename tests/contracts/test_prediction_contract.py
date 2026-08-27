"""The frozen prediction contract.

Most of these are refusals. The contract's job is to stand between an article
and a target outcome, and the failure it exists to prevent is a system that
appears to forecast terrorism while counting newspaper reports about protests.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from pramaanx.contract import (
    CONTRACT_VERSION,
    FORECAST_UNIT,
    HORIZON_DAYS,
    INCIDENT_DATE_TOLERANCE_DAYS,
    PRIMARY_OUTPUT,
    AbstentionReason,
    ClassificationInput,
    Completion,
    DistrictForecast,
    DualAdjudication,
    ExclusionReason,
    ExplosiveCause,
    ForecastWindow,
    Incident,
    IncidentKey,
    IncidentReport,
    MotivationEvidence,
    NonConformingPathError,
    Resolution,
    TargetClass,
    VerifierDecision,
    assert_conforming,
    build_incident,
    classify,
    contract_hash,
)

CUTOFF = datetime(2026, 8, 27, tzinfo=UTC)
OCCURRED = date(2026, 8, 20)


def _key(
    target_class: TargetClass = TargetClass.IED_ATTACK,
    completion: Completion = Completion.COMPLETED,
    district: str = "IN-MH-MUMBAI-CITY",
    occurred_on: date = OCCURRED,
) -> IncidentKey:
    return IncidentKey(
        target_class=target_class,
        completion=completion,
        district_id=district,
        occurred_on=occurred_on,
    )


def _report(index: int, source: str = "gdelt") -> IncidentReport:
    return IncidentReport(
        report_id=f"rep_{index}",
        observation_id=f"obs_{index}",
        source_id=source,
        first_observed_at=CUTOFF - timedelta(days=1),
    )


class TestReportsAreNotIncidents:
    def test_twenty_reports_of_one_bombing_are_one_incident(self) -> None:
        """The numerator defect, pinned.

        The base-rate path counted twenty articles as twenty events. Here they
        attach to one incident and increment nothing.
        """
        incident = build_incident(
            _key(),
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.ATTRIBUTED_DEVICE,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            ),
            [_report(i, source="gdelt" if i % 2 else "reliefweb") for i in range(20)],
        )
        assert incident.supporting_report_count == 20
        assert incident.counts_as_outcome
        # One outcome, whatever the report count.
        assert len({incident.incident_id}) == 1

    def test_incident_identity_is_stable_and_content_derived(self) -> None:
        assert _key().incident_id() == _key().incident_id()
        assert _key().incident_id().startswith("inc_")

    def test_same_class_same_district_adjacent_days_is_one_incident(self) -> None:
        """Reports disagree about dates, especially across midnight."""
        first = _key(occurred_on=date(2026, 8, 20))
        second = _key(occurred_on=date(2026, 8, 21))
        assert first.same_incident_as(second)

    def test_a_wider_date_gap_is_two_incidents(self) -> None:
        """Merging them would suppress the clustering the model must detect."""
        first = _key(occurred_on=date(2026, 8, 20))
        far = _key(occurred_on=date(2026, 8, 20) + timedelta(days=INCIDENT_DATE_TOLERANCE_DAYS + 1))
        assert not first.same_incident_as(far)

    def test_different_districts_are_never_the_same_incident(self) -> None:
        assert not _key(district="IN-MH-MUMBAI-CITY").same_incident_as(
            _key(district="IN-KL-ERNAKULAM")
        )


class TestExclusions:
    @pytest.mark.parametrize(
        ("exclusion", "label"),
        [
            (ExclusionReason.PROTEST, "a protest is not an attack"),
            (ExclusionReason.ARREST, "an arrest is not an attack"),
            (ExclusionReason.ARMS_RECOVERY, "an arms recovery is not an attack"),
            (ExclusionReason.RHETORIC_OR_THREAT, "a threat is not an attack"),
            (ExclusionReason.ORDINARY_CRIME, "ordinary crime is not an attack"),
        ],
    )
    def test_excluded_categories_are_negative(self, exclusion: ExclusionReason, label: str) -> None:
        result = classify(ClassificationInput(observed_exclusion=exclusion))
        assert result.resolution is Resolution.NEGATIVE, label
        assert result.exclusion is exclusion

    def test_an_exclusion_survives_an_official_attribution(self) -> None:
        """Order matters: an attributed arrest is still an arrest.

        Applying motivation first would turn every NIA arrest press release
        into a positive attack outcome.
        """
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.TERRORISM,
                observed_exclusion=ExclusionReason.ARREST,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            )
        )
        assert result.resolution is Resolution.NEGATIVE
        assert result.exclusion is ExclusionReason.ARREST

    def test_a_negative_incident_must_name_why(self) -> None:
        with pytest.raises(ValidationError, match="names no exclusion reason"):
            Incident(
                incident_id="inc_x",
                key=_key(),
                resolution=Resolution.NEGATIVE,
            )


class TestExplosives:
    def test_an_accidental_explosion_is_not_terrorism(self) -> None:
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.ACCIDENTAL,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            )
        )
        assert result.resolution is Resolution.NEGATIVE
        assert result.exclusion is ExclusionReason.ACCIDENTAL_EXPLOSION

    def test_an_unresolved_ied_is_uncertain_not_positive(self) -> None:
        """Gas cylinders, quarry accidents and ordnance disposal all explode."""
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.UNRESOLVED,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            )
        )
        assert result.resolution is Resolution.ADJUDICATION_REQUIRED

    def test_an_ied_with_no_stated_cause_is_uncertain(self) -> None:
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                motivation_evidence=MotivationEvidence.CLAIM_OF_RESPONSIBILITY,
            )
        )
        assert result.resolution is Resolution.ADJUDICATION_REQUIRED

    def test_military_disposal_is_excluded_not_uncertain(self) -> None:
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.MILITARY_TRAINING_OR_DISPOSAL,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            )
        )
        assert result.resolution is Resolution.NEGATIVE
        assert result.exclusion is ExclusionReason.MILITARY_TRAINING_OR_DISPOSAL

    def test_an_attributed_device_with_motivation_is_positive(self) -> None:
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.ATTRIBUTED_DEVICE,
                motivation_evidence=MotivationEvidence.JUDICIAL_FINDING,
            )
        )
        assert result.resolution is Resolution.POSITIVE
        assert result.target_class is TargetClass.IED_ATTACK


class TestMotivationIsNeverInferred:
    def test_no_motivation_evidence_is_uncertain_not_positive(self) -> None:
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.POLITICALLY_MOTIVATED_ARMED_ASSAULT,
                motivation_evidence=MotivationEvidence.NONE,
            )
        )
        assert result.resolution is Resolution.ADJUDICATION_REQUIRED
        assert "not inferable" in result.reason

    @pytest.mark.parametrize(
        "evidence",
        [
            MotivationEvidence.CLAIM_OF_RESPONSIBILITY,
            MotivationEvidence.OFFICIAL_ATTRIBUTION,
            MotivationEvidence.JUDICIAL_FINDING,
        ],
    )
    def test_only_the_three_admissible_kinds_establish_motivation(
        self, evidence: MotivationEvidence
    ) -> None:
        result = classify(
            ClassificationInput(proposed_class=TargetClass.LWE_ATTACK, motivation_evidence=evidence)
        )
        assert result.resolution is Resolution.POSITIVE

    def test_a_positive_incident_cannot_be_stored_without_motivation(self) -> None:
        """Belt and braces: the model refuses even if a classifier were wrong."""
        with pytest.raises(ValidationError, match="never by reporting language"):
            Incident(
                incident_id="inc_x",
                key=_key(),
                resolution=Resolution.POSITIVE,
                motivation_evidence=MotivationEvidence.NONE,
            )


class TestCompletion:
    def test_attempted_is_distinct_from_completed(self) -> None:
        base = {
            "proposed_class": TargetClass.ARMED_INSURGENT_ATTACK,
            "motivation_evidence": MotivationEvidence.CLAIM_OF_RESPONSIBILITY,
        }
        completed = classify(ClassificationInput(**base, completion=Completion.COMPLETED))
        attempted = classify(ClassificationInput(**base, completion=Completion.ATTEMPTED))
        assert completed.resolution is Resolution.POSITIVE
        assert attempted.resolution is Resolution.POSITIVE
        # Distinct incidents, so distinct base rates.
        assert (
            _key(completion=Completion.COMPLETED).incident_id()
            != _key(completion=Completion.ATTEMPTED).incident_id()
        )
        assert not _key(completion=Completion.COMPLETED).same_incident_as(
            _key(completion=Completion.ATTEMPTED)
        )

    def test_a_foiled_plot_is_not_a_positive_target(self) -> None:
        """Counting foiled plots would score the forecaster on police success."""
        result = classify(
            ClassificationInput(
                proposed_class=TargetClass.TERRORISM,
                completion=Completion.FOILED,
                motivation_evidence=MotivationEvidence.OFFICIAL_ATTRIBUTION,
            )
        )
        assert result.resolution is Resolution.NEGATIVE


class TestWindowAndCutoff:
    def test_the_window_is_open_at_the_cutoff(self) -> None:
        """An incident at the cutoff instant is evidence, not outcome."""
        window = ForecastWindow(cutoff_at=CUTOFF)
        assert not window.contains(CUTOFF)
        assert window.contains(CUTOFF + timedelta(seconds=1))
        assert window.contains(CUTOFF + timedelta(days=HORIZON_DAYS))
        assert not window.contains(CUTOFF + timedelta(days=HORIZON_DAYS, seconds=1))

    def test_evidence_published_after_the_cutoff_cannot_resolve_the_forecast(self) -> None:
        """The leakage rule, expressed against report availability.

        A report that became available after the cutoff is outside the evidence
        set for a forecast made at that cutoff, however early the incident it
        describes occurred.
        """
        window = ForecastWindow(cutoff_at=CUTOFF)
        late = _report(1)
        late = late.model_copy(update={"first_observed_at": CUTOFF + timedelta(days=2)})
        admissible = [r for r in (_report(0), late) if r.first_observed_at <= window.cutoff_at]
        assert [r.report_id for r in admissible] == ["rep_0"]

    def test_the_horizon_is_rolling_from_each_cutoff(self) -> None:
        first = ForecastWindow(cutoff_at=CUTOFF)
        second = ForecastWindow(cutoff_at=CUTOFF + timedelta(days=7))
        assert second.start > first.start
        assert (second.end - second.start).days == HORIZON_DAYS


class TestForecastOutput:
    def test_an_abstention_carries_no_probability(self) -> None:
        with pytest.raises(ValidationError, match="abstention with a number"):
            DistrictForecast(
                district_id="IN-KL-ERNAKULAM",
                target_class=TargetClass.LWE_ATTACK,
                window=ForecastWindow(cutoff_at=CUTOFF),
                probability=0.4,
                abstained=True,
                abstention_reason=AbstentionReason.INSUFFICIENT_COVERAGE,
            )

    def test_an_abstention_must_name_its_reason(self) -> None:
        with pytest.raises(ValidationError, match="without naming a reason"):
            DistrictForecast(
                district_id="IN-KL-ERNAKULAM",
                target_class=TargetClass.LWE_ATTACK,
                window=ForecastWindow(cutoff_at=CUTOFF),
                abstained=True,
            )

    def test_a_non_abstention_must_produce_a_number(self) -> None:
        with pytest.raises(ValidationError, match="neither abstained nor produced"):
            DistrictForecast(
                district_id="IN-KL-ERNAKULAM",
                target_class=TargetClass.LWE_ATTACK,
                window=ForecastWindow(cutoff_at=CUTOFF),
            )


class TestGoldSchema:
    def test_two_decisions_require_two_people(self) -> None:
        decision = VerifierDecision(
            verifier_id="v1", decided_at=CUTOFF, resolution=Resolution.POSITIVE
        )
        with pytest.raises(ValidationError, match="require two people"):
            DualAdjudication(incident_id="inc_x", first=decision, second=decision.model_copy())

    def test_disagreement_is_reported_per_field(self) -> None:
        """Agreeing it is positive while disagreeing on district is disagreement."""
        first = VerifierDecision(
            verifier_id="v1",
            decided_at=CUTOFF,
            resolution=Resolution.POSITIVE,
            district_id="IN-MH-MUMBAI-CITY",
        )
        second = first.model_copy(update={"verifier_id": "v2", "district_id": "IN-MH-THANE"})
        adjudication = DualAdjudication(incident_id="inc_x", first=first, second=second)
        assert adjudication.disagreements() == ("district_id",)
        assert not adjudication.agreed
        assert not adjudication.resolved

    def test_a_third_adjudicator_resolves_a_disagreement(self) -> None:
        first = VerifierDecision(
            verifier_id="v1", decided_at=CUTOFF, resolution=Resolution.POSITIVE
        )
        second = first.model_copy(update={"verifier_id": "v2", "resolution": Resolution.NEGATIVE})
        final = first.model_copy(update={"verifier_id": "v3"})
        adjudication = DualAdjudication(
            incident_id="inc_x", first=first, second=second, final=final
        )
        assert "resolution" in adjudication.disagreements()
        assert adjudication.resolved

    def test_a_verifier_may_decline_to_decide(self) -> None:
        decision = VerifierDecision(
            verifier_id="v1",
            decided_at=CUTOFF,
            resolution=Resolution.ADJUDICATION_REQUIRED,
            could_not_decide=True,
        )
        assert decision.could_not_decide


class TestConformance:
    def test_the_event_mention_base_rate_path_may_not_forecast(self) -> None:
        with pytest.raises(NonConformingPathError, match="undeduplicated"):
            assert_conforming("base_rate/event_mention")

    def test_the_refusal_forbids_relabelling_as_a_workaround(self) -> None:
        with pytest.raises(NonConformingPathError, match="must not be relabelled"):
            assert_conforming("base_rate/event_mention")

    def test_an_unlisted_path_is_permitted(self) -> None:
        # Returns None and does not raise; the conformance check is a gate, not
        # an allowlist that every future path must be added to by hand.
        assert assert_conforming("adjudicated_incidents") is None


class TestFrozen:
    #: Changing what is predicted must be a deliberate, reviewed act.
    PINNED_VERSION = "1.0.0"
    PINNED_HASH = "sha256:7956d58bc3e86039b67d2c714dcac00f5d9ad90eb25d157245013cf4f86c54c0"

    def test_the_contract_version_is_pinned(self) -> None:
        assert CONTRACT_VERSION == self.PINNED_VERSION

    def test_the_unit_and_horizon_are_frozen(self) -> None:
        assert FORECAST_UNIT == "district"
        assert HORIZON_DAYS == 30
        assert PRIMARY_OUTPUT == "binary_occurrence"

    def test_the_hash_is_stable_within_a_version(self) -> None:
        assert contract_hash() == contract_hash()

    def test_the_contract_matches_its_pin(self) -> None:
        """Changing what is predicted must be deliberate and reviewed.

        A target class added, an exclusion removed, the horizon changed -- any
        of them moves this hash. Bump CONTRACT_VERSION and update the pin in the
        same commit, so the change is argued about rather than merged.
        """
        assert contract_hash() == self.PINNED_HASH, (
            "the prediction contract changed. Bump CONTRACT_VERSION and update "
            "PINNED_HASH in this test, in the same commit as the change."
        )

    def test_adjudication_required_incidents_are_not_scoreable(self) -> None:
        """Excluded from both classes rather than defaulted to either."""
        incident = build_incident(
            _key(),
            ClassificationInput(
                proposed_class=TargetClass.IED_ATTACK,
                explosive_cause=ExplosiveCause.UNRESOLVED,
            ),
        )
        assert incident.resolution is Resolution.ADJUDICATION_REQUIRED
        assert not incident.scoreable
        assert not incident.counts_as_outcome


class TestGeneratorConformance:
    def test_the_base_rate_generator_declares_itself_non_conforming(self) -> None:
        """The marking must live on the code, not only in a dict of strings."""
        from pramaanx.generators.base_rate import BaseRateGenerator

        assert BaseRateGenerator.contract_conforming is False
        with pytest.raises(NonConformingPathError):
            assert_conforming(BaseRateGenerator.contract_path)
