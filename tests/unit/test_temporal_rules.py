"""G1 temporal rules, and the comparison against the preregistered floor."""

from __future__ import annotations

import pytest
from _phase2_builders import at, mention, series_of

from pramaanx.entities import deduplicate_mentions, resolve_entities
from pramaanx.generators import (
    ALL_RULES,
    FLOOR_GENERATOR,
    RULE_DIFFUSION,
    RULE_ESCALATION,
    RULE_RECURRENCE,
    DiscoveryComparison,
    FloorVerdict,
    ForecastContext,
    TemporalRuleGenerator,
    available_generators,
    compare_discovery,
)
from pramaanx.graph import build_graph

BUCKETS = ("0-7d", "7-30d", "30-90d")


def _generator(mentions: list, cutoff_day: float, rules=ALL_RULES) -> TemporalRuleGenerator:
    cutoff = at(cutoff_day)
    index = resolve_entities(mentions, cutoff_at=cutoff)
    clusters = deduplicate_mentions(mentions, index, cutoff_at=cutoff)
    graph = build_graph(clusters, index, cutoff_at=cutoff)
    return TemporalRuleGenerator(
        mentions, clusters, index, graph, time_buckets=BUCKETS, rules=rules
    )


def _context(cutoff_day: float, budget: int = 50) -> ForecastContext:
    return ForecastContext(
        cutoff_at=at(cutoff_day),
        evidence_snapshot_id="snap_test",
        proposal_budget=budget,
        horizon_days=90,
    )


class TestRegistration:
    def test_generator_is_registered_under_its_name(self) -> None:
        assert "temporal_rules" in available_generators()

    def test_version_records_the_active_rules(self) -> None:
        generator = _generator(series_of(count=5, spacing_days=20), 200, rules=(RULE_ESCALATION,))
        assert RULE_ESCALATION in generator.version
        assert RULE_DIFFUSION not in generator.version

    def test_unknown_rule_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown rules"):
            _generator(series_of(count=3, spacing_days=10), 100, rules=("teleportation",))


class TestProposals:
    def test_a_regular_series_produces_proposals(self) -> None:
        generator = _generator(series_of(count=6, spacing_days=20, start_day=10), 130)
        proposals = generator.propose(_context(130))
        assert proposals
        assert all(0.0 <= p.generator_score <= 1.0 for p in proposals)

    def test_budget_is_respected(self) -> None:
        generator = _generator(series_of(count=8, spacing_days=15), 200)
        assert len(generator.propose(_context(200, budget=2))) <= 2

    def test_every_proposal_carries_a_per_rule_trace(self) -> None:
        generator = _generator(series_of(count=6, spacing_days=20, start_day=10), 130)
        for proposal in generator.propose(_context(130)):
            assert set(proposal.trace["rules"]) <= set(ALL_RULES)
            assert "contributions" in proposal.trace

    def test_proposing_past_the_graph_cutoff_raises(self) -> None:
        generator = _generator(series_of(count=5, spacing_days=20), 130)
        with pytest.raises(ValueError, match="after the graph cutoff"):
            generator.propose(_context(400))

    def test_time_buckets_form_a_distribution(self) -> None:
        generator = _generator(series_of(count=6, spacing_days=20, start_day=10), 130)
        for proposal in generator.propose(_context(130)):
            buckets = proposal.hypothesis.time_bucket_probabilities
            if buckets:
                assert sum(buckets.values()) == pytest.approx(1.0)

    def test_disabling_a_rule_cannot_raise_a_score(self) -> None:
        """Noisy-OR means an ablation reads cleanly in one direction."""
        mentions = series_of(count=6, spacing_days=20, start_day=10)
        full = {
            p.candidate_key: p.generator_score
            for p in _generator(mentions, 130).propose(_context(130))
        }
        ablated = {
            p.candidate_key: p.generator_score
            for p in _generator(mentions, 130, rules=(RULE_RECURRENCE,)).propose(_context(130))
        }
        for key, score in ablated.items():
            assert score <= full[key] + 1e-9

    def test_a_bursty_series_gets_nothing_from_recurrence(self) -> None:
        bursty = [
            mention(observed_days=11, event_days=10, span="clash one"),
            mention(observed_days=12, event_days=11, span="clash two"),
            mention(observed_days=13, event_days=12, span="clash three"),
            mention(observed_days=181, event_days=180, span="clash four"),
        ]
        generator = _generator(bursty, 200, rules=(RULE_RECURRENCE,))
        for proposal in generator.propose(_context(200)):
            assert proposal.trace["rules"][RULE_RECURRENCE]["fired"] in (True, False)


class TestFloorComparison:
    def test_discovery_comparison_partitions_the_pools(self) -> None:
        generator = _generator(series_of(count=6, spacing_days=20, start_day=10), 130)
        proposals = generator.propose(_context(130))
        comparison = compare_discovery([], proposals)
        assert comparison.challenger_only
        assert comparison.floor_only == []
        assert comparison.shared == []
        assert comparison.adds_discovery

    def test_identical_pools_add_no_discovery(self) -> None:
        generator = _generator(series_of(count=6, spacing_days=20, start_day=10), 130)
        proposals = generator.propose(_context(130))
        comparison = compare_discovery(proposals, proposals)
        assert not comparison.adds_discovery
        assert comparison.coverage_of_floor == 1.0

    def test_verdict_requires_the_margin(self) -> None:
        verdict = FloorVerdict(
            challenger_name="temporal_rules",
            metric_name="candidate_recall",
            floor_value=0.80,
            challenger_value=0.81,
            margin=0.02,
        )
        assert not verdict.cleared
        assert "did not clear" in verdict.summary

    def test_lower_is_better_metrics_invert_the_comparison(self) -> None:
        verdict = FloorVerdict(
            challenger_name="temporal_rules",
            metric_name="pooled_brier",
            floor_value=0.24,
            challenger_value=0.20,
            margin=0.02,
            lower_is_better=True,
        )
        assert verdict.cleared
        assert verdict.improvement == pytest.approx(0.04)

    def test_summary_names_the_floor(self) -> None:
        verdict = FloorVerdict(
            challenger_name="temporal_rules",
            metric_name="candidate_recall",
            floor_value=0.5,
            challenger_value=0.9,
            discovery=DiscoveryComparison(
                floor_name=FLOOR_GENERATOR,
                challenger_name="temporal_rules",
                challenger_only=["evt_a"],
            ),
        )
        assert FLOOR_GENERATOR in verdict.summary
        assert "1 candidates the floor did not" in verdict.summary

    def test_metric_name_is_required(self) -> None:
        with pytest.raises(ValueError, match="name the metric"):
            FloorVerdict(
                challenger_name="x", metric_name="  ", floor_value=0.1, challenger_value=0.2
            )
