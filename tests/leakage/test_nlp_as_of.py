"""Nothing published after the cutoff may reach, or change, a result.

The leakage this file guards is quieter than the obvious kind. Nobody sets out
to feed a forecaster tomorrow's newspaper. What happens instead is that a
revision arrives, a batch is reprocessed, and the "as of March 2nd" output
silently becomes the March 9th output -- with the same name, the same file, and
a different answer. Every metric computed on it is then measuring a corpus that
did not exist at the cutoff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from _news_builders import record
from _nlp_builders import CUTOFF, StubResolver
from pramaanx.ingest.article_content import latest_as_of
from pramaanx.nlp.pipeline import (
    CutoffViolationError,
    NlpOptions,
    batch_hash,
    run_batch,
    run_deterministic_nlp,
)

EARLY = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
LATE = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)

BODY = "Security forces recovered an IED near the market in Kishtwar on Sunday."
REVISED = "Security forces recovered an IED near the market in Kishtwar. Two were held."


def at(moment: datetime, *, body: str = BODY, url: str = "https://example.test/story/1", **extra):  # type: ignore[no-untyped-def]
    return record(
        url=url,
        headline="IED recovered",
        body=body,
        retrieved_at=moment,
        first_resolvable_at=moment,
        **extra,
    )


class TestPostCutoffArticles:
    def test_a_post_cutoff_article_is_refused_outright(self) -> None:
        with pytest.raises(CutoffViolationError, match="after the cutoff"):
            run_deterministic_nlp(at(LATE), cutoff=CUTOFF)

    def test_the_boundary_is_inclusive_of_the_cutoff_instant(self) -> None:
        # first_resolvable_at <= cutoff, so an article resolvable exactly at the
        # cutoff is admissible. An off-by-one here silently discards a day.
        assert run_deterministic_nlp(at(CUTOFF), cutoff=CUTOFF).text_available is True
        with pytest.raises(CutoffViolationError):
            run_deterministic_nlp(at(CUTOFF + timedelta(microseconds=1)), cutoff=CUTOFF)

    def test_future_articles_cannot_change_an_earlier_batch(self) -> None:
        # Required behaviour: injecting later documents must leave the earlier
        # output byte-identical, not merely similar.
        early = tuple(at(EARLY, url=f"https://example.test/s/{index}") for index in range(3))
        late = tuple(
            at(LATE, url=f"https://example.test/late/{index}", body="A later blast report.")
            for index in range(3)
        )
        before = run_batch(early, cutoff=CUTOFF)
        after = run_batch(early + late, cutoff=CUTOFF)
        assert batch_hash(before) == batch_hash(after)
        assert [r.model_dump() for r in before] == [r.model_dump() for r in after]

    def test_a_future_article_contributes_nothing_at_all(self) -> None:
        early = (at(EARLY),)
        late = at(LATE, url="https://example.test/other", body="Unrelated later text.")
        assert {r.observation_id for r in run_batch((*early, late), cutoff=CUTOFF)} == {
            r.observation_id for r in run_batch(early, cutoff=CUTOFF)
        }


class TestRevisions:
    def _pair(self):  # type: ignore[no-untyped-def]
        original = at(EARLY)
        revision = at(
            LATE,
            body=REVISED,
            revision_of=original.observation_id,
            revision_index=1,
        )
        return original, revision

    def test_a_post_cutoff_revision_cannot_change_the_earlier_result(self) -> None:
        # Required behaviour 7. The revision is a separate record with a later
        # first_resolvable_at, so the cutoff filters it and the earlier version
        # is returned unchanged.
        original, revision = self._pair()
        alone = run_batch((original,), cutoff=CUTOFF)
        with_revision = run_batch((original, revision), cutoff=CUTOFF)
        assert batch_hash(alone) == batch_hash(with_revision)

    def test_the_earlier_text_is_what_gets_processed(self) -> None:
        original, revision = self._pair()
        results = run_batch((original, revision), cutoff=CUTOFF)
        assert len(results) == 1
        joined = " ".join(span.text for span in results[0].sentence_spans)
        assert "Two were held" not in joined

    def test_the_revision_becomes_visible_after_its_own_cutoff(self) -> None:
        # The revision is not lost, only deferred. A later cutoff sees it.
        original, revision = self._pair()
        later = run_batch((original, revision), cutoff=datetime(2026, 3, 10, tzinfo=UTC))
        current = latest_as_of((original, revision), datetime(2026, 3, 10, tzinfo=UTC))
        assert len(current) == 1
        assert current[0].observation_id == revision.observation_id
        assert len(later) == 2


class TestAnchorVersusCutoff:
    def test_the_cutoff_does_not_move_relative_dates(self) -> None:
        # The anchor is publication time. Interpreting "yesterday" against the
        # cutoff instead would make the same article mean different things in
        # different backtest folds -- the subtlest leak in the system.
        rec = at(EARLY, body="The recovery was made yesterday.")
        early_fold = run_deterministic_nlp(rec, cutoff=CUTOFF)
        late_fold = run_deterministic_nlp(rec, cutoff=datetime(2026, 4, 1, tzinfo=UTC))
        assert [m.normalized_start for m in early_fold.temporal_mentions] == [
            m.normalized_start for m in late_fold.temporal_mentions
        ]

    def test_only_the_cutoff_field_differs_between_folds(self) -> None:
        rec = at(EARLY, body="The recovery was made yesterday in Kishtwar.")
        early = run_deterministic_nlp(rec, cutoff=CUTOFF).model_dump()
        late = run_deterministic_nlp(rec, cutoff=datetime(2026, 4, 1, tzinfo=UTC)).model_dump()
        differing = {key for key in early if early[key] != late[key]}
        assert differing == {"cutoff_at"}


class TestResolutionIsAsOf:
    def test_the_resolver_receives_the_cutoff_not_today(self) -> None:
        # A district that split after the cutoff must not be visible at it, and
        # the only way the resolver can honour that is by being told the date.
        resolver = StubResolver()
        run_deterministic_nlp(at(EARLY), cutoff=CUTOFF, options=NlpOptions(resolver=resolver))
        assert resolver.queries
        assert all(query.as_of == CUTOFF for query in resolver.queries)

    def test_a_later_cutoff_asks_a_different_question(self) -> None:
        resolver = StubResolver()
        later = datetime(2026, 4, 1, tzinfo=UTC)
        run_deterministic_nlp(at(EARLY), cutoff=later, options=NlpOptions(resolver=resolver))
        assert all(query.as_of == later for query in resolver.queries)


class TestOutcomeIsolation:
    def test_the_result_carries_no_outcome_field(self) -> None:
        # The deterministic stage runs before anything is known about whether an
        # event occurred, and its schema must give no place to put such a thing.
        dumped = run_deterministic_nlp(at(EARLY), cutoff=CUTOFF).model_dump()
        for banned in ("outcome", "label", "occurred", "incident_count", "target"):
            assert not any(banned in key for key in dumped), banned
