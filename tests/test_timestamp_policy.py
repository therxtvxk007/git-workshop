"""One timestamp policy, enforced everywhere a document enters the system.

The defect these tests were written against: `eval/availability.py` rejects a
naive timestamp as undecidable, while `stage0_ingest/validate.py` quietly
repaired one with `replace(tzinfo=UTC)`. Stage 0 runs first, so by the time the
availability rule saw a document the naive timestamp had already been invented
away, and `prepare()` admitted input the documented contract says must be
refused.

Two rules that must hold together are not two rules. These tests exercise the
complete ingestion path rather than either module alone, because that is where
the contradiction lived and neither module's own tests could see it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaan_x.config import Config
from pramaan_x.types import Document

NAIVE_PUB = datetime(2025, 3, 1, 12, 0)
AWARE_PUB = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)


def _doc(doc_id: str, published, retrieved, **meta) -> Document:
    return Document(
        doc_id=doc_id,
        source_id="wire_a_national",
        title="Chennai update",
        text=(
            "In Chennai, reservoir levels approached the seasonal spill threshold. "
            "The water board published its quarterly audit report on Monday. "
            "Officials at the port trust declined to comment on the revised survey findings."
        ),
        published_at=published,
        retrieved_at=retrieved,
        meta={"source_family": "wire_a", "synth_target": "Chennai|flood", **meta},
    )


# ------------------------------------------------- the end-to-end control ---


def test_stage0_must_not_invent_a_timezone(strict_timestamp_config):
    """END-TO-END NEGATIVE CONTROL for requirement 1.

    Fails on the committed implementation: `validate_timestamps` rewrote the
    naive stamp to UTC and returned the document as OK, so the whole benchmark
    ingestion path admitted it.
    """
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    naive = _doc("naive-pub", NAIVE_PUB, AWARE_PUB + timedelta(hours=1))
    result = run_stage0([naive], strict_timestamp_config.stage0)

    assert [d.doc_id for d in result.documents] == [], (
        "strict ingestion admitted a document with a naive published_at; "
        "the availability contract says it must be rejected, not repaired"
    )
    reasons = dict(result.validation.rejected)
    assert "naive-pub" in reasons
    assert "naive" in reasons["naive-pub"].lower()
    assert result.validation.n_naive_timestamp == 1


def test_stage0_rejects_a_naive_retrieved_at(strict_timestamp_config):
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    doc = _doc("naive-ret", AWARE_PUB, datetime(2025, 3, 1, 13, 0))
    result = run_stage0([doc], strict_timestamp_config.stage0)
    assert [d.doc_id for d in result.documents] == []
    assert result.validation.n_naive_timestamp == 1
    assert "naive" in dict(result.validation.rejected)["naive-ret"].lower()


def test_aware_timestamps_still_pass(strict_timestamp_config):
    """The policy must reject naive stamps without rejecting everything."""
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    doc = _doc("aware", AWARE_PUB, AWARE_PUB + timedelta(hours=1))
    result = run_stage0([doc], strict_timestamp_config.stage0)
    assert [d.doc_id for d in result.documents] == ["aware"]
    assert result.validation.n_naive_timestamp == 0


def test_a_non_utc_offset_is_preserved_not_flattened(strict_timestamp_config):
    """Converting +05:30 to UTC is arithmetic; stamping UTC onto a naive value
    is invention. Only the second is forbidden."""
    from datetime import timezone

    from pramaan_x.stage0_ingest.pipeline import run_stage0

    kolkata = timezone(timedelta(hours=5, minutes=30))
    pub = datetime(2025, 3, 1, 17, 30, tzinfo=kolkata)  # == 12:00Z
    doc = _doc("offset", pub, pub + timedelta(hours=1))
    (kept,) = run_stage0([doc], strict_timestamp_config.stage0).documents
    assert kept.published_at == AWARE_PUB
    assert kept.published_at.utcoffset() == timedelta(0)


# --------------------------------------------- the non-strict escape hatch ---


def test_utc_assuming_mode_exists_but_must_be_asked_for(utc_assuming_config):
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    doc = _doc("naive-pub", NAIVE_PUB, AWARE_PUB + timedelta(hours=1))
    result = run_stage0([doc], utc_assuming_config.stage0)
    assert [d.doc_id for d in result.documents] == ["naive-pub"]
    assert result.validation.n_assumed_utc == 1


def test_strict_evaluation_refuses_a_utc_assuming_corpus(utc_assuming_config):
    """NEGATIVE CONTROL: the escape hatch must not be reachable from the
    method whose results are reported."""
    from pramaan_x.eval.harness import prepare
    from pramaan_x.timestamps import TimestampPolicyError

    with pytest.raises(TimestampPolicyError, match="strict"):
        prepare(utc_assuming_config, days=120, seed=1, n_locations=3, n_event_types=2)


def test_strict_is_the_default(strict_timestamp_config):
    """A policy you have to remember to switch on is not a policy."""
    assert Config().stage0.timestamp_policy == "strict"
    assert strict_timestamp_config.stage0.timestamp_policy == "strict"


# ------------------------------------------- the trusted-snapshot tightening ---


@pytest.mark.parametrize("value", ["false", "False", "true", "0", "1", 1, 0, [], {}, None, "yes"])
def test_trusted_snapshot_flag_requires_exactly_true(value):
    """NEGATIVE CONTROL: `bool(meta.get(flag))` treated the string "false" as
    trust, which is the classic YAML/JSON round-trip bug. Only the boolean
    `True` may admit a document with no acquisition time."""
    from pramaan_x.eval.availability import (
        TRUSTED_SNAPSHOT_FLAG,
        Rejection,
        classify,
        is_trusted_snapshot,
    )

    doc = _doc("t", AWARE_PUB, None, **{TRUSTED_SNAPSHOT_FLAG: value})
    assert is_trusted_snapshot(doc) is False, f"{value!r} was treated as trusted"
    assert classify(doc, AWARE_PUB + timedelta(days=1)) is Rejection.MISSING_ACQUISITION_TIME


def test_trusted_snapshot_flag_accepts_only_the_boolean():
    from pramaan_x.eval.availability import (
        TRUSTED_SNAPSHOT_FLAG,
        classify,
        is_trusted_snapshot,
    )

    doc = _doc("t", AWARE_PUB, None, **{TRUSTED_SNAPSHOT_FLAG: True})
    assert is_trusted_snapshot(doc) is True
    assert classify(doc, AWARE_PUB + timedelta(days=1)) is None


# ------------------------------------------------ the artefact keeps the reason ---


def test_the_artefact_records_timestamp_rejections(strict_timestamp_config, tmp_path):
    """A rejection nobody can see afterwards is indistinguishable from a
    document that never existed."""
    from pramaan_x.eval.harness import prepare, run_method
    from pramaan_x.eval.oracle_target_retrieval import STRICT

    prep = prepare(strict_timestamp_config, days=150, seed=3, n_locations=4, n_event_types=3)
    # `select=False`: a 150-day corpus leaves the selection and regression
    # windows empty, and the selector correctly refuses rather than falling
    # back to the test window. Operating-point selection is covered end to end
    # in tests/test_selection.py; what is under test here is the ingestion
    # record.
    res = run_method(
        prep,
        strict_timestamp_config,
        STRICT,
        stages=("rerank",),
        results_dir=tmp_path,
        require_clean_source=False,
        write=False,
        select=False,
    )
    ingestion = res.payload["extra"]["stage0"]["validation"]
    assert "naive_timestamp" in ingestion
    assert "assumed_utc" in ingestion
    assert ingestion["assumed_utc"] == 0, "strict runs must never assume a timezone"
    assert res.payload["extra"]["timestamp_policy"] == "strict"
