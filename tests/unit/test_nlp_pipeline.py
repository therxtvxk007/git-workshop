"""The deterministic stage end to end: grounded, offline, and free of models."""

from __future__ import annotations

import socket
import sys
from datetime import UTC, datetime

import pytest

from _news_builders import record
from _nlp_builders import CUTOFF, StubResolver, alias, registry_of
from pramaanx.ingest.article_content import LicenceClass
from pramaanx.nlp.pipeline import (
    CutoffViolationError,
    NlpOptions,
    batch_hash,
    document_text,
    run_batch,
    run_deterministic_nlp,
)
from pramaanx.nlp.schemas import PIPELINE_VERSION, CrimeVerdict, ResolutionStatus

BODY = (
    "Security forces recovered an IED near the market in Kishtwar on 4 March 2026, "
    'police said. "We are still investigating," said Superintendent of Police Ravi Kumar. '
    "The blast in 2008 killed two people."
)


def article(**kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.setdefault("headline", "IED recovered in district search")
    kwargs.setdefault("body", BODY)
    return record(**kwargs)  # type: ignore[arg-type]


class TestDocumentAssembly:
    def test_headline_and_body_are_located(self) -> None:
        rec = article()
        text, headline, body = document_text(rec)
        assert headline is not None and body is not None
        assert text[headline.start : headline.end] == rec.headline
        assert text[body.start : body.end] == rec.body_text

    def test_a_headline_only_article_has_no_body_span(self) -> None:
        rec = article(licence=LicenceClass.METADATA_ONLY)
        text, headline, body = document_text(rec)
        assert headline is not None
        assert body is None
        assert text == rec.headline

    def test_a_withheld_article_assembles_to_nothing(self) -> None:
        text, headline, body = document_text(article(licence=LicenceClass.UNKNOWN))
        assert text == ""
        assert headline is None and body is None


class TestCutoffAdmissibility:
    def test_a_post_cutoff_article_is_refused(self) -> None:
        # Required behaviour 6. Refused before any text is touched, so it cannot
        # influence a cache, a statistic or a timing signal.
        late = article(
            retrieved_at=datetime(2026, 3, 9, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 9, tzinfo=UTC),
        )
        with pytest.raises(CutoffViolationError, match="after the cutoff"):
            run_deterministic_nlp(late, cutoff=CUTOFF)

    def test_an_admissible_article_is_processed(self) -> None:
        assert run_deterministic_nlp(article(), cutoff=CUTOFF).text_available is True

    def test_a_naive_cutoff_is_refused(self) -> None:
        # Required behaviour 25.
        with pytest.raises(CutoffViolationError, match="timezone-aware"):
            run_deterministic_nlp(article(), cutoff=datetime(2026, 3, 5))  # noqa: DTZ001

    def test_content_about_the_future_is_not_rejected(self) -> None:
        # An article describing the future is normal; discarding it would
        # remove the most forecast-relevant sentences in the corpus.
        rec = article(body="Forces will be deployed in the district in three days.")
        result = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert any(mention.is_future_claim for mention in result.temporal_mentions)


class TestSpansAreGrounded:
    def test_every_returned_span_slices_the_original(self) -> None:
        # Required behaviour 1, at the level the rest of the system consumes.
        rec = article()
        text, _, _ = document_text(rec)
        result = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert result.verify_spans(text) == ()

    def test_candidate_spans_are_whole_sentences(self) -> None:
        rec = article()
        result = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert result.candidate_spans
        sentences = [span.model_dump() for span in result.sentence_spans]
        assert all(span.model_dump() in sentences for span in result.candidate_spans)

    def test_the_original_hash_is_of_the_assembled_document(self) -> None:
        rec = article()
        text, _, _ = document_text(rec)
        from pramaanx.nlp.normalize import original_text_hash

        assert run_deterministic_nlp(rec, cutoff=CUTOFF).original_text_hash == (
            original_text_hash(text)
        )


class TestLicenceIsRespectedByConstruction:
    def test_a_withheld_article_yields_a_result_with_no_spans(self) -> None:
        # Dropping it would bias coverage towards permissively licensed
        # sources; processing it as text would be a licensing incident.
        result = run_deterministic_nlp(article(licence=LicenceClass.UNKNOWN), cutoff=CUTOFF)
        assert result.text_available is False
        assert result.sentence_spans == ()
        assert result.ordinary_crime_assessment.verdict is CrimeVerdict.INSUFFICIENT_EVIDENCE

    def test_no_withheld_body_text_reaches_the_result(self) -> None:
        result = run_deterministic_nlp(article(licence=LicenceClass.UNKNOWN), cutoff=CUTOFF)
        assert "Kishtwar" not in result.model_dump_json()

    def test_a_snippet_licence_limits_what_spans_can_quote(self) -> None:
        rec = article(licence=LicenceClass.SNIPPET_ONLY)
        text, _, _ = document_text(rec)
        result = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert result.verify_spans(text) == ()
        assert len(text) <= len(rec.headline or "") + 300 + 2


class TestInjectedBackends:
    def test_locations_are_unresolved_without_a_resolver(self) -> None:
        result = run_deterministic_nlp(article(), cutoff=CUTOFF)
        assert result.location_mentions
        assert all(m.status is ResolutionStatus.UNRESOLVED for m in result.location_mentions)

    def test_an_injected_resolver_is_used(self) -> None:
        options = NlpOptions(resolver=StubResolver({"Kishtwar": ("dist_kishtwar",)}))
        result = run_deterministic_nlp(article(), cutoff=CUTOFF, options=options)
        assert any(m.status is ResolutionStatus.RESOLVED for m in result.location_mentions)

    def test_no_actors_are_found_without_a_registry(self) -> None:
        assert run_deterministic_nlp(article(), cutoff=CUTOFF).actor_mentions == ()

    def test_an_injected_registry_is_used(self) -> None:
        options = NlpOptions(actor_registry=registry_of(alias("Red Star Brigade", "actor_1")))
        rec = article(body="The Red Star Brigade claimed the attack in the district.")
        result = run_deterministic_nlp(rec, cutoff=CUTOFF, options=options)
        assert [m.canonical_actor_id for m in result.actor_mentions] == ["actor_1"]

    def test_the_alias_version_is_recorded(self) -> None:
        options = NlpOptions(actor_registry=registry_of(alias("Red Star Brigade", "actor_1")))
        result = run_deterministic_nlp(article(), cutoff=CUTOFF, options=options)
        assert result.alias_version == options.actor_registry.alias_version

    def test_options_do_not_share_a_mutable_registry(self) -> None:
        # A shared default instance is one assignment away from leaking one
        # caller's actor table into every other caller's run.
        assert NlpOptions().actor_registry is not NlpOptions().actor_registry


class TestProvenance:
    def test_the_pipeline_version_is_recorded(self) -> None:
        assert run_deterministic_nlp(article(), cutoff=CUTOFF).pipeline_version == PIPELINE_VERSION

    def test_all_four_timestamps_survive(self) -> None:
        rec = article(modified_at=datetime(2026, 3, 1, 8, 0, tzinfo=UTC))
        result = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert result.published_at == rec.published_at
        assert result.modified_at == rec.modified_at
        assert result.retrieved_at == rec.retrieved_at
        assert result.first_resolvable_at == rec.first_resolvable_at

    def test_the_cutoff_is_recorded_separately_from_the_anchor(self) -> None:
        # The anchor is linguistic; the cutoff is admissibility. Conflating them
        # would make one article mean different things in different folds.
        result = run_deterministic_nlp(article(), cutoff=CUTOFF)
        assert result.cutoff_at == CUTOFF
        assert all(m.anchor_time != CUTOFF for m in result.temporal_mentions)

    def test_the_snapshot_hash_travels_through(self) -> None:
        rec = article()
        stamped = rec.model_copy(update={"snapshot_hash": "sha256:abc"})
        assert run_deterministic_nlp(stamped, cutoff=CUTOFF).source_snapshot_hash == "sha256:abc"


class TestNoModelsAndNoNetwork:
    def test_importing_the_package_loads_no_heavy_backend(self) -> None:
        # Required behaviour 21. A model download at import time would make
        # every test run depend on a network and a cache directory.
        for module in ("torch", "transformers", "gliner", "spacy", "litellm"):
            assert module not in sys.modules

    def test_running_the_pipeline_opens_no_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Required behaviour 22, asserted rather than assumed.
        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("the deterministic stage attempted a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        result = run_deterministic_nlp(article(), cutoff=CUTOFF)
        assert result.text_available is True

    def test_no_probability_is_produced(self) -> None:
        # A deterministic preprocessor that scored articles would be an
        # unevaluated model upstream of the evaluated one.
        dumped = run_deterministic_nlp(article(), cutoff=CUTOFF).model_dump()
        for banned in ("probability", "score", "risk", "likelihood"):
            assert not any(banned in key for key in dumped)


class TestBatching:
    def test_a_batch_is_sorted_by_observation_id(self) -> None:
        records = tuple(article(url=f"https://example.test/s/{index}") for index in range(4))
        results = run_batch(records, cutoff=CUTOFF)
        assert [r.observation_id for r in results] == sorted(r.observation_id for r in results)

    def test_inadmissible_records_are_skipped_not_processed(self) -> None:
        late = article(
            url="https://example.test/late",
            retrieved_at=datetime(2026, 3, 9, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 9, tzinfo=UTC),
        )
        results = run_batch((article(), late), cutoff=CUTOFF)
        assert late.observation_id not in {r.observation_id for r in results}

    def test_strict_mode_refuses_instead_of_skipping(self) -> None:
        late = article(
            retrieved_at=datetime(2026, 3, 9, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 9, tzinfo=UTC),
        )
        with pytest.raises(CutoffViolationError):
            run_batch((late,), cutoff=CUTOFF, skip_inadmissible=False)

    def test_a_batch_hash_is_stable(self) -> None:
        records = tuple(article(url=f"https://example.test/s/{index}") for index in range(3))
        assert batch_hash(run_batch(records, cutoff=CUTOFF)) == batch_hash(
            run_batch(records, cutoff=CUTOFF)
        )
