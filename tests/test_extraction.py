"""Tests for event extraction and its LLM/offline swap."""

from evpred.extraction import LLMExtractor, RuleExtractor, annotate, get_extractor
from evpred.schema import Document
import datetime as dt


def test_rule_extractor_finds_actor_action_target():
    events = RuleExtractor().extract("Police arrested twelve demonstrators in the capital.")
    assert len(events) == 1
    assert events[0].action == "arrested"
    assert events[0].actor == "police"
    assert events[0].target == "demonstrators"
    assert events[0].polarity < 0


def test_polarity_sign_separates_conflict_from_cooperation():
    hostile = RuleExtractor().extract("Riots erupted downtown.")[0]
    friendly = RuleExtractor().extract("The government agreed to reopen talks.")[0]
    assert hostile.polarity < 0 < friendly.polarity


def test_temporal_expressions_are_captured():
    events = RuleExtractor().extract("The union threatened a strike on Friday.")
    assert events[0].time_ref.lower() == "on friday"


def test_text_without_events_yields_nothing():
    assert RuleExtractor().extract("Rainfall was above the seasonal average.") == []
    assert RuleExtractor().extract("") == []


def test_strongest_action_anchors_a_multi_verb_sentence():
    events = RuleExtractor().extract("Officials warned that riots could follow.")
    assert events[0].action == "riots"  # -0.9 beats "warned" at -0.3


def test_annotate_populates_documents_in_place():
    docs = [Document(doc_id="a", text="Police arrested demonstrators.",
                     date=dt.date(2024, 1, 1), region="r")]
    annotate(docs, RuleExtractor())
    assert docs[0].n_events == 1


def test_llm_extractor_falls_back_and_counts_it():
    extractor = LLMExtractor(api_key=None)
    events = extractor.extract("Police arrested demonstrators in the capital.")
    assert not extractor.available
    assert extractor.n_fallback == 1
    assert events and events[0].action == "arrested"  # fallback still works


def test_llm_response_parsing_handles_prose_and_garbage():
    payload = """Here is the JSON you asked for:
    [{"actor": "union", "action": "STRIKE", "target": "ministry", "polarity": -0.7,
      "confidence": 0.9, "time_ref": "Friday", "quote": "the union struck"},
     {"actor": "x", "polarity": 0.1},
     {"actor": "gov", "action": "agree", "polarity": "not-a-number"}]
    Hope that helps."""
    events = LLMExtractor._parse(payload)
    assert len(events) == 2                 # the action-less row is dropped
    assert events[0].action == "strike"     # lowercased
    assert events[1].polarity == 0.0        # unparseable value clamped to 0


def test_llm_parse_rejects_malformed_payloads():
    assert LLMExtractor._parse("no json here") == []
    assert LLMExtractor._parse("[{broken") == []


def test_get_extractor_selects_backends():
    assert isinstance(get_extractor("rule"), RuleExtractor)
    assert isinstance(get_extractor("llm"), LLMExtractor)
    assert isinstance(get_extractor("auto"), (RuleExtractor, LLMExtractor))
    try:
        get_extractor("nonsense")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown extractor kind")
