"""Joint entity/relation/event extraction.

Two backends behind one interface:

  * `GLiNERRelexExtractor` -- the deployment path. One encoder pass produces
    entities and relations for arbitrary types supplied at inference time, at a
    fraction of the cost of prompting a 27B model per document. This is the
    whole reason the cascade can afford to look at every document.

  * `RuleExtractor` -- the offline path. Gazetteer plus learned lexicon plus
    shallow relation patterns. Weaker, but it is a real extractor with real
    failure modes, so consensus and conflict logic can be exercised against it.

Both emit the same `EventTuple`, including `publication_cutoff_valid`, which is
set here and never recomputed downstream: the guarantee belongs at the point of
extraction, where the document's publication date is still in hand.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..types import Document, EventTuple
from .bm25 import tokenize
from .lexical import LexicalIndicators

# Shallow relation patterns. Ordered: the first match wins, so specific
# patterns must precede generic ones.
RELATION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("deployed_to", re.compile(r"\b(units?|forces|troops|patrols|personnel)\b[^.]{0,40}?\b(redeployed|deployed|moved|stationed)\b", re.IGNORECASE)),
    ("issued", re.compile(r"\b(issued|extended|imposed|declared|announced)\b\s+(?:a|an|the)?\s*([\w\s]{3,40})", re.IGNORECASE)),
    ("rejected", re.compile(r"\b(rejected|refused|declined|opposed)\b\s+(?:a|an|the)?\s*([\w\s]{3,40})", re.IGNORECASE)),
    ("reported", re.compile(r"\b(reported|recorded|observed|flagged|described)\b\s+(?:a|an|the)?\s*([\w\s]{3,40})", re.IGNORECASE)),
    ("exceeded", re.compile(r"\b(exceeded|approached|reached|rose|climbed|surpassed)\b\s+([\w\s]{3,40})", re.IGNORECASE)),
    ("disrupted", re.compile(r"\b(suspended|halted|blocked|closed|obstructed|delayed)\b\s+([\w\s]{3,40})", re.IGNORECASE)),
    ("planned", re.compile(r"\b(called for|announced|voted to|planned|scheduled)\b\s+(?:a|an|the)?\s*([\w\s]{3,40})", re.IGNORECASE)),
)

SOURCE_RELIABILITY_DEFAULT = 0.6


class Extractor(Protocol):
    name: str

    def extract(self, docs: Sequence[Document], *, origin: datetime | None = None
                ) -> list[EventTuple]: ...


@dataclass
class RuleExtractor:
    """Gazetteer + learned lexicon + shallow relation patterns."""

    gazetteer: set[str] = field(default_factory=set)
    lexicon: LexicalIndicators | None = None
    event_types: tuple[str, ...] = ()
    source_reliability: dict[str, float] = field(default_factory=dict)
    min_confidence: float = 0.05
    # Absolute floor on the winning event-type score. Without it the margin
    # rule alone will happily label a pure-boilerplate document, because a
    # margin can be wide between two near-zero scores.
    min_type_score: float = 2.0
    name: str = "rule"

    def extract(self, docs: Sequence[Document], *, origin: datetime | None = None
                ) -> list[EventTuple]:
        out: list[EventTuple] = []
        for doc in docs:
            text = doc.full_text
            loc = self._location(text)
            et, et_conf = self._event_type(text)
            if et is None:
                continue
            subject, relation, obj = self._relation(text, loc)
            reliability = self.source_reliability.get(
                doc.meta.get("source_family", ""), SOURCE_RELIABILITY_DEFAULT
            )
            conf = float(min(0.99, et_conf * (0.5 + 0.5 * reliability)))
            if conf < self.min_confidence:
                continue
            out.append(EventTuple(
                subject=subject, relation=relation, object=obj,
                event_type=et,
                event_time=None,           # a precursor asserts no event time
                location=loc or "unknown",
                source_id=doc.source_id, doc_id=doc.doc_id,
                extractor_confidence=conf,
                supporting_span=self._span(text, et),
                publication_cutoff_valid=(origin is None or doc.published_at < origin),
                extractors=(self.name,),
            ))
        return out

    # ---------------------------------------------------------- pieces ---

    def _location(self, text: str) -> str | None:
        for name in self.gazetteer:
            if name.lower() in text.lower():
                return name
        return None

    def _event_type(self, text: str) -> tuple[str | None, float]:
        if self.lexicon is None or not self.event_types:
            return (None, 0.0)
        scored = [(et, self.lexicon.score(text, et)) for et in self.event_types]
        scored.sort(key=lambda kv: -kv[1])
        best, best_s = scored[0]
        runner = scored[1][1] if len(scored) > 1 else 0.0
        if best_s < self.min_type_score:
            return (None, 0.0)
        # Confidence is the *margin*, squashed. A document that scores equally
        # for three event types is ambiguous, and stage 3 should see it.
        margin = (best_s - runner) / (best_s + 1e-9)
        return best, float(min(0.99, 0.35 + 0.65 * margin))

    def _relation(self, text: str, loc: str | None) -> tuple[str, str, str]:
        for rel, pat in RELATION_PATTERNS:
            m = pat.search(text)
            if m:
                groups = [g for g in m.groups() if g]
                subj = (loc or groups[0]).strip()
                obj = groups[-1].strip()[:60] if len(groups) > 1 else groups[0].strip()[:60]
                return subj, rel, obj
        return (loc or "unknown"), "mentions", " ".join(tokenize(text)[:8])

    def _span(self, text: str, event_type: str) -> str:
        """Return the sentence carrying the most lexicon weight -- the evidence
        an analyst will actually be shown."""
        if self.lexicon is None:
            return text[:160]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if not sentences:
            return text[:160]
        best = max(sentences, key=lambda s: self.lexicon.score(s, event_type))
        return best.strip()[:240]


@dataclass
class GLiNERRelexExtractor:
    """Deployment backend: joint zero-shot NER + relation extraction.

    Entity and relation labels are supplied at call time, so adding a new event
    type costs a string in a config file, not a retraining run.
    """

    model_name: str = "knowledgator/gliner-relex-large-v1.0"
    entity_labels: tuple[str, ...] = ("location", "organisation", "person",
                                      "facility", "equipment", "date")
    relation_labels: tuple[str, ...] = ("deployed_to", "issued", "rejected",
                                        "reported", "exceeded", "disrupted",
                                        "planned", "located_in", "affiliated_with")
    threshold: float = 0.35
    device: str | None = None
    batch_size: int = 16
    name: str = "gliner-relex"
    _model: object | None = None

    def _load(self):
        if self._model is None:
            from gliner import GLiNER

            self._model = GLiNER.from_pretrained(self.model_name)
            if self.device:
                self._model = self._model.to(self.device)
        return self._model

    def extract(self, docs: Sequence[Document], *, origin: datetime | None = None
                ) -> list[EventTuple]:
        model = self._load()
        out: list[EventTuple] = []
        for start in range(0, len(docs), self.batch_size):
            batch = docs[start : start + self.batch_size]
            texts = [d.full_text for d in batch]
            results = model.batch_predict_relations(
                texts, self.entity_labels, self.relation_labels, threshold=self.threshold
            )
            for doc, rels in zip(batch, results, strict=True):
                for r in rels:
                    out.append(EventTuple(
                        subject=r["source"], relation=r["relation"], object=r["target"],
                        event_type=r.get("event_type", r["relation"]),
                        event_time=None,
                        location=r.get("location", "unknown"),
                        source_id=doc.source_id, doc_id=doc.doc_id,
                        extractor_confidence=float(r.get("score", self.threshold)),
                        supporting_span=r.get("span", doc.full_text[:240]),
                        publication_cutoff_valid=(origin is None or doc.published_at < origin),
                        extractors=(self.name,),
                    ))
        return out


def consensus(
    tuple_sets: Iterable[list[EventTuple]],
    *,
    agreement_boost: float = 0.25,
) -> list[EventTuple]:
    """Merge extractors. Agreement raises confidence; disagreement is *kept*.

    The alternative -- picking a winner when extractors disagree -- throws away
    the single most useful signal the ensemble produces, which is that the
    document is hard. Conflicted tuples are flagged and routed to stage 3
    rather than silently resolved here.
    """
    merged: dict[tuple, EventTuple] = {}
    for tuples in tuple_sets:
        for t in tuples:
            k = (t.doc_id, *t.key())
            if k not in merged:
                merged[k] = t
                continue
            prev = merged[k]
            prev.extractors = tuple(sorted(set(prev.extractors) | set(t.extractors)))
            prev.extractor_confidence = min(
                0.99, max(prev.extractor_confidence, t.extractor_confidence) + agreement_boost
            )

    # Flag documents where extractors produced incompatible event types.
    by_doc: dict[str, list[EventTuple]] = {}
    for t in merged.values():
        by_doc.setdefault(t.doc_id, []).append(t)
    for tuples in by_doc.values():
        types = {t.event_type for t in tuples}
        if len(types) > 1:
            for t in tuples:
                t.conflict = True
    return list(merged.values())
