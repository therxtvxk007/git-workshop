"""Tests for feature construction and the lookahead guard."""

import datetime as dt

import numpy as np
import pytest

from evpred.extraction import RuleExtractor, annotate
from evpred.features import (
    EVENT_FEATURE_NAMES,
    GROUP_FEATURE_NAMES,
    DecayConfig,
    assert_no_lookahead,
    event_features,
    group_features,
    instance_matrix,
)
from evpred.schema import Bag, BagGroup, Document

ORIGIN = dt.date(2024, 3, 1)


def make_doc(days_before: int, text: str, doc_id: str = "d", region: str = "r"):
    doc = Document(doc_id=doc_id, text=text, date=ORIGIN - dt.timedelta(days=days_before),
                   region=region, source="test")
    annotate([doc], RuleExtractor())
    return doc


def make_group(docs, horizon=7):
    by_date = {}
    for d in docs:
        by_date.setdefault(d.date, Bag(region=d.region, date=d.date)).documents.append(d)
    return BagGroup(region="r", origin=ORIGIN, horizon_days=horizon,
                    bags=sorted(by_date.values(), key=lambda b: b.date), label=1)


def test_lookahead_guard_rejects_documents_at_or_after_origin():
    good = make_group([make_doc(1, "The union threatened a strike.")])
    assert_no_lookahead(good)  # does not raise

    for offset in (0, -1):  # on the origin, and after it
        bad = make_group([make_doc(offset, "The union threatened a strike.")])
        with pytest.raises(ValueError, match="lookahead"):
            assert_no_lookahead(bad)


def test_decay_weight_halves_at_the_half_life():
    decay = DecayConfig(half_life_days=5.0)
    assert decay.weight(0.0) == pytest.approx(1.0)
    assert decay.weight(5.0) == pytest.approx(0.5)
    assert decay.weight(10.0) == pytest.approx(0.25)
    assert DecayConfig(half_life_days=0.0).weight(99.0) == 1.0


def test_recent_negative_news_outweighs_old_news():
    """G3: identical text should count for more when it is more recent."""
    text = "Police arrested demonstrators and the union threatened a strike."
    recent = make_group([make_doc(1, text, "recent")])
    old = make_group([make_doc(13, text, "old")])
    decay = DecayConfig(half_life_days=5.0)
    i = GROUP_FEATURE_NAMES.index("neg_intensity_decayed")
    assert group_features(recent, decay, 14)[i] > group_features(old, decay, 14)[i]


def test_event_features_have_stable_width():
    empty = Document(doc_id="e", text="", date=ORIGIN, region="r")
    populated = make_doc(1, "Police arrested demonstrators. The union agreed to talks.")
    assert event_features(empty).shape == (len(EVENT_FEATURE_NAMES),)
    assert event_features(populated).shape == (len(EVENT_FEATURE_NAMES),)


def test_event_features_capture_polarity_sign():
    hostile = make_doc(1, "Riots broke out and police arrested demonstrators.")
    friendly = make_doc(1, "The government agreed to reopen talks and signed a deal.")
    i = EVENT_FEATURE_NAMES.index("mean_polarity")
    assert event_features(hostile)[i] < 0 < event_features(friendly)[i]


def test_group_features_are_finite_and_correct_width():
    docs = [make_doc(k, "Police arrested demonstrators in the capital.", f"d{k}")
            for k in range(1, 10)]
    feats = group_features(make_group(docs), DecayConfig(), 14)
    assert feats.shape == (len(GROUP_FEATURE_NAMES),)
    assert np.all(np.isfinite(feats))


def test_empty_group_yields_zero_features():
    feats = group_features(make_group([]), DecayConfig(), 14)
    assert feats.shape == (len(GROUP_FEATURE_NAMES),)
    assert np.allclose(feats, 0.0)


def test_instance_matrix_appends_recency_columns():
    docs = [make_doc(k, "The union threatened a strike.", f"d{k}") for k in (1, 5)]
    for d in docs:
        d.embedding = np.ones(8)
    X, ordered = instance_matrix(make_group(docs), DecayConfig(half_life_days=5.0))
    assert X.shape == (2, 8 + len(EVENT_FEATURE_NAMES) + 2)
    assert [d.doc_id for d in ordered] == ["d5", "d1"]  # chronological
    assert X[1, -2] > X[0, -2]  # the newer document carries more recency weight
