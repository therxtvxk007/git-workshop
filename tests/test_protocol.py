"""The locked temporal protocol.

These tests assert the protocol's *guarantees*, not that its constructor runs:
that the windows are ordered and disjoint, that the embargo is wide enough for
the label lookahead that actually crosses it, that origins never postdate the
event they serve, and that there is no path through this module that produces a
random split.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

import pytest

from pramaan_x.eval import protocol as protocol_module
from pramaan_x.eval.protocol import (
    AVAILABILITY_RULE,
    PERMITTED_FITTING,
    QUERY_GENERATION_RULE,
    ProtocolError,
    TemporalProtocol,
)

START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)


@pytest.fixture
def proto() -> TemporalProtocol:
    return TemporalProtocol.from_span(START, END)


def test_windows_are_ordered_and_disjoint(proto):
    assert proto.train_start < proto.train_end
    assert proto.train_end < proto.calibration_start
    assert proto.calibration_start < proto.calibration_end
    assert proto.calibration_end < proto.test_start
    assert proto.test_start < proto.test_end


def test_embargo_is_at_least_the_label_lookahead(proto):
    """An embargo narrower than the forward lookahead used to build labels does
    not separate the windows, whatever it is called."""
    assert proto.effective_embargo_days >= proto.label_lookahead_days
    assert (proto.calibration_start - proto.train_end).days >= proto.effective_embargo_days
    assert (proto.test_start - proto.calibration_end).days >= proto.effective_embargo_days


def test_label_cutoff_keeps_the_lookahead_inside_the_training_window(proto):
    assert proto.label_cutoff == proto.train_end - timedelta(days=proto.label_lookahead_days)
    assert proto.label_cutoff > proto.train_start


def test_a_narrow_embargo_is_rejected():
    with pytest.raises(ProtocolError, match="embargo"):
        TemporalProtocol(
            train_start=START,
            train_end=START + timedelta(days=100),
            calibration_start=START + timedelta(days=101),
            calibration_end=START + timedelta(days=140),
            test_start=START + timedelta(days=141),
            test_end=START + timedelta(days=200),
            embargo_days=1,
            label_lookahead_days=21,
            origin_stride_days=7,
        )


def test_out_of_order_windows_are_rejected():
    with pytest.raises(ProtocolError):
        TemporalProtocol(
            train_start=START + timedelta(days=300),
            train_end=START + timedelta(days=10),
            calibration_start=START + timedelta(days=40),
            calibration_end=START + timedelta(days=60),
            test_start=START + timedelta(days=90),
            test_end=END,
            embargo_days=21,
            label_lookahead_days=21,
            origin_stride_days=7,
        )


def test_naive_bounds_are_rejected():
    with pytest.raises(ProtocolError, match="timezone aware"):
        TemporalProtocol.from_span(datetime(2025, 1, 1), END)


def test_a_corpus_too_short_for_the_embargo_is_refused():
    with pytest.raises(ProtocolError, match=r"no room|test window"):
        TemporalProtocol.from_span(START, START + timedelta(days=30))


# ----------------------------------------------------------- origins ---


def test_origins_tile_the_window_and_stay_inside_it(proto):
    origins = proto.origins("test")
    assert origins[0] == proto.test_start
    assert all(proto.test_start <= o < proto.test_end for o in origins)
    gaps = {(b - a).days for a, b in pairwise(origins)}
    assert gaps == {proto.origin_stride_days}


def test_origin_for_never_postdates_the_event(proto):
    """The decisive property. Rounding an event up to the next grid point would
    put the index past the event it is supposed to precede."""
    event = proto.test_start + timedelta(days=40, hours=13)
    origin = proto.origin_for("test", event)
    assert origin is not None
    assert origin <= event
    assert event - origin < timedelta(days=proto.origin_stride_days)


def test_origin_for_an_event_outside_the_window_is_none(proto):
    assert proto.origin_for("test", proto.train_start + timedelta(days=1)) is None
    assert proto.origin_for("test", proto.test_end + timedelta(days=1)) is None


def test_origin_for_normalises_the_event_timezone(proto):
    tokyo = timezone(timedelta(hours=9))
    event = (proto.test_start + timedelta(days=10)).astimezone(tokyo)
    assert proto.origin_for("test", event) == proto.origin_for(
        "test", proto.test_start + timedelta(days=10)
    )


def test_contains_is_half_open(proto):
    assert proto.contains("test", proto.test_start)
    assert not proto.contains("test", proto.test_end)
    assert not proto.contains("train", proto.train_end)


def test_unknown_window_is_an_error(proto):
    with pytest.raises(ProtocolError, match="unknown window"):
        proto.window("holdout")


# ---------------------------------------------------------- identity ---


def test_fingerprint_changes_with_any_temporal_decision(proto):
    other = TemporalProtocol.from_span(START, END, origin_stride_days=14)
    assert proto.fingerprint() != other.fingerprint()
    assert proto.fingerprint() == TemporalProtocol.from_span(START, END).fingerprint()


def test_serialised_protocol_carries_the_rules_it_locks(proto):
    d = proto.to_dict()
    assert d["availability_rule"] == AVAILABILITY_RULE
    assert d["query_generation_rule"] == QUERY_GENERATION_RULE
    assert d["permitted_fitting"] == list(PERMITTED_FITTING)
    assert d["n_test_origins"] == len(proto.origins("test"))
    assert "not an event-forecasting protocol" in d["query_generation_rule"]


def test_the_protocol_module_contains_no_random_split():
    """A guard on the whole module rather than on one function: temporal splits
    only, and no shuffling helper may be introduced later without this failing."""
    source = inspect.getsource(protocol_module)
    for banned in ("train_test_split", "shuffle", "random.sample", "KFold"):
        assert banned not in source, f"{banned} must not appear in the protocol"


def test_no_permitted_fitting_operation_may_touch_the_test_window(proto):
    """The locked window selects nothing. Every entry in the permitted-fitting
    list names the training window or a fold origin, never the test window."""
    for entry in proto.permitted_fitting:
        lowered = entry.lower()
        if "test" in lowered:
            # The only permitted mention of the test window is a prohibition.
            assert "never the test window" in lowered, entry
        assert any(
            w in entry
            for w in (
                "training-window",
                "before the fold origin",
                "selection-window",
                "regression-window",
            )
        ), entry


def test_the_calibration_window_exists_to_absorb_selection(proto):
    """If there were no calibration window, any threshold or width choice would
    have to be made on the test window or on nothing."""
    assert proto.calibration_end > proto.calibration_start
    assert proto.calibration_end <= proto.test_start
