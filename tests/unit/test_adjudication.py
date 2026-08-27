"""Candidate adjudication: belief states, audit trails and abstention."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pramaanx.adjudication import (
    BeliefState,
    BeliefUpdate,
    EvidenceWeightAdjudicator,
    UpdateKind,
    Verdict,
    adjudicate_all,
    independence_counts,
    logit,
    logit_mean,
    logit_spread,
    sigmoid,
)
from pramaanx.generators.base import CandidateProposal
from pramaanx.schemas.event import EventHypothesis
from pramaanx.schemas.evidence import EvidenceRef

AS_OF = datetime(2025, 7, 1, tzinfo=UTC)


def _ref(cluster: str, stance: str, observation: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        observation_id=observation or f"obs_{cluster}",
        claim=f"{stance} claim from {cluster}",
        stance=stance,  # type: ignore[arg-type]
        independence_cluster=cluster,
        reliability=0.7,
    )


def _proposal(score: float = 0.3, evidence: list[EvidenceRef] | None = None) -> CandidateProposal:
    return CandidateProposal(
        hypothesis=EventHypothesis(
            event_id="evt_test",
            event_type="protest",
            actor_ids=["actor_a"],
            location_cells={"IN-KL": 1.0},
            time_bucket_probabilities={"0-7d": 1.0},
            evidence=evidence or [],
        ),
        generator_name="test",
        generator_score=score,
    )


class TestLogOddsMath:
    def test_the_round_trip_is_exact_enough_to_replay(self) -> None:
        for probability in (0.01, 0.25, 0.5, 0.75, 0.99):
            assert sigmoid(logit(probability)) == pytest.approx(probability, abs=1e-9)

    def test_a_large_logit_does_not_overflow(self) -> None:
        """A confident belief can carry a logit past the exp() ceiling."""
        assert sigmoid(1000.0) == pytest.approx(1.0)
        assert sigmoid(-1000.0) == pytest.approx(0.0)

    def test_averaging_in_logit_space_beats_averaging_probabilities(self) -> None:
        """Two confident agreeing trials should not be dragged toward 0.5."""
        trials = [0.9, 0.92]
        assert logit_mean(trials) > 0.9
        assert logit_mean(trials) > sum(trials) / len(trials) - 0.01

    def test_agreement_and_disagreement_are_distinguishable(self) -> None:
        agreed = logit_spread([0.6, 0.6, 0.6])
        split = logit_spread([0.1, 0.95, 0.5])
        assert agreed == 0.0
        assert split > 1.0


class TestIndependenceCounting:
    def test_reprints_of_one_story_count_once(self) -> None:
        """The difference between calibrated and merely confident."""
        refs = [_ref("wire_1", "supports", f"obs_{i}") for i in range(50)]
        support, contra, repeated = independence_counts(refs)
        assert support == 1
        assert contra == 0
        assert repeated == 49

    def test_support_and_contradiction_are_counted_separately(self) -> None:
        refs = [
            _ref("a", "supports"),
            _ref("b", "supports"),
            _ref("c", "contradicts"),
            _ref("d", "context"),
        ]
        assert independence_counts(refs) == (2, 1, 0)


class TestAbstention:
    def test_thin_evidence_abstains_rather_than_guessing(self) -> None:
        adjudicator = EvidenceWeightAdjudicator()
        belief = adjudicator.adjudicate(_proposal(0.42), [_ref("a", "supports")], as_of=AS_OF)
        assert belief.verdict is Verdict.INSUFFICIENT
        assert belief.is_abstention
        assert belief.probability == 0.42

    def test_fifty_reprints_of_one_source_still_abstain(self) -> None:
        """The case the whole independence-counting machinery exists for."""
        refs = [_ref("wire_1", "supports", f"obs_{i}") for i in range(50)]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        assert belief.verdict is Verdict.INSUFFICIENT
        assert belief.independent_support == 1
        assert belief.repeated_items == 49

    def test_an_abstention_may_not_move_its_own_number(self) -> None:
        with pytest.raises(ValidationError, match="abstention's label"):
            BeliefState(
                candidate_id="evt_x",
                verdict=Verdict.INSUFFICIENT,
                prior=0.3,
                probability=0.7,
            )


class TestVerdicts:
    def test_independent_support_raises_the_belief(self) -> None:
        refs = [_ref("a", "supports"), _ref("b", "supports"), _ref("c", "supports")]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        assert belief.verdict is Verdict.SUPPORTED
        assert belief.probability > 0.3

    def test_contradiction_lowers_it(self) -> None:
        refs = [_ref(letter, "contradicts") for letter in "abc"]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.6), refs, as_of=AS_OF)
        assert belief.verdict is Verdict.CONTRADICTED
        assert belief.probability < 0.6

    def test_a_corpus_that_disagrees_is_disputed_not_averaged(self) -> None:
        """DISPUTED is a statement about the corpus, not a middle score."""
        refs = [
            _ref("a", "supports"),
            _ref("b", "supports"),
            _ref("c", "contradicts"),
        ]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.4), refs, as_of=AS_OF)
        assert belief.verdict is Verdict.DISPUTED
        assert belief.independent_support == 2
        assert belief.independent_contradiction == 1


class TestAuditTrail:
    def test_replaying_the_updates_reproduces_the_probability(self) -> None:
        """The property that makes the trail worth keeping.

        If replay disagrees with the stored number, something moved the belief
        without recording why -- which is the failure the whole design exists
        to make impossible.
        """
        refs = [_ref("a", "supports"), _ref("b", "supports"), _ref("c", "contradicts")]
        belief = EvidenceWeightAdjudicator(trials=1).adjudicate(_proposal(0.35), refs, as_of=AS_OF)
        assert belief.replay_probability() == pytest.approx(belief.probability, abs=1e-6)

    def test_every_update_names_a_kind_and_a_reason(self) -> None:
        refs = [_ref("a", "supports"), _ref("b", "supports")]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        assert belief.updates
        for update in belief.updates:
            assert update.kind in set(UpdateKind)
            assert update.rationale

    def test_repetition_is_recorded_even_though_it_changes_nothing(self) -> None:
        """ "We saw this fifty times from one source" is itself a finding."""
        refs = [_ref("a", "supports"), _ref("a", "supports", "obs_2"), _ref("b", "supports")]
        belief = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        kinds = [update.kind for update in belief.updates]
        assert UpdateKind.REPETITION_DISCOUNT in kinds
        discount = next(u for u in belief.updates if u.kind is UpdateKind.REPETITION_DISCOUNT)
        assert discount.delta_logit == 0.0

    def test_a_belief_update_is_recorded_in_log_odds(self) -> None:
        update = BeliefUpdate(kind=UpdateKind.PRIOR, delta_logit=0.0, rationale="x")
        assert "+0.0000" in str(update)


class TestDeterminismAndTrials:
    def test_the_same_input_gives_the_same_belief(self) -> None:
        refs = [_ref("a", "supports"), _ref("b", "supports")]
        first = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        second = EvidenceWeightAdjudicator().adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        assert first.probability == second.probability
        assert first.trial_disagreement == second.trial_disagreement

    def test_trials_differ_from_each_other_or_they_measure_nothing(self) -> None:
        refs = [_ref("a", "supports"), _ref("b", "supports")]
        belief = EvidenceWeightAdjudicator(trials=5).adjudicate(_proposal(0.3), refs, as_of=AS_OF)
        assert belief.trial_disagreement > 0.0

    def test_the_version_records_the_settings_that_produced_it(self) -> None:
        version = EvidenceWeightAdjudicator(trials=7).version
        assert "t7" in version
        assert version.startswith("evidence_weight@")


class TestUnresolvedFields:
    def test_a_candidate_with_no_actor_says_so(self) -> None:
        proposal = CandidateProposal(
            hypothesis=EventHypothesis(event_id="evt_y", event_type="protest"),
            generator_name="test",
            generator_score=0.3,
        )
        belief = EvidenceWeightAdjudicator().adjudicate(
            proposal, [_ref("a", "supports"), _ref("b", "supports")], as_of=AS_OF
        )
        assert "actor_ids" in belief.unresolved_fields
        assert "location_cells" in belief.unresolved_fields


class TestBatch:
    def test_the_report_counts_abstentions_and_disputes(self) -> None:
        strong = _proposal(0.3, [_ref("a", "supports"), _ref("b", "supports")])
        thin = _proposal(0.3, [_ref("c", "supports")])
        thin.hypothesis.event_id = "evt_thin"
        beliefs, report = adjudicate_all(EvidenceWeightAdjudicator(), [strong, thin], as_of=AS_OF)
        assert report.candidates == 2
        assert report.abstentions == 1
        assert report.abstention_rate == 0.5
        assert len(beliefs) == 2

    def test_order_is_stable_regardless_of_input_order(self) -> None:
        a = _proposal(0.3, [_ref("x", "supports"), _ref("y", "supports")])
        b = _proposal(0.4, [_ref("x", "supports"), _ref("y", "supports")])
        b.hypothesis.event_id = "evt_aaa"
        forward, _ = adjudicate_all(EvidenceWeightAdjudicator(), [a, b], as_of=AS_OF)
        reverse, _ = adjudicate_all(EvidenceWeightAdjudicator(), [b, a], as_of=AS_OF)
        assert [x.candidate_id for x in forward] == [x.candidate_id for x in reverse]
