"""Event extraction: unstructured English text -> structured event tuples.

Two interchangeable backends behind one protocol:

``RuleExtractor``
    Dependency-free, deterministic, offline. Uses a verb lexicon with CAMEO-ish
    polarity weights plus shallow actor/target heuristics. Fast enough for the
    full corpus and good enough to make the downstream pipeline testable
    without a network.

``LLMExtractor``
    Schema-constrained extraction via the Anthropic Messages API. This is the
    component the surveyed rule-based systems (Pundit, MLN) most needed: it
    generalises to out-of-domain text without a human writing new first-order
    rules, which is gap G2 in ``docs/01-survey-gap-analysis.md``.

Both return ``list[Event]``. Downstream code never learns which one ran, so an
offline backtest and an LLM backtest are directly comparable.
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterable, Protocol, Sequence

from .schema import Document, Event

# --------------------------------------------------------------------------
# Lexicon. Weights are signed conflict intensity, loosely following the CAMEO
# Goldstein scale sign convention: negative = conflictual, positive = cooperative.
# --------------------------------------------------------------------------

_ACTION_LEXICON: dict[str, float] = {
    # conflictual
    "protest": -0.6, "protests": -0.6, "protested": -0.6, "protesting": -0.6,
    "demonstrate": -0.5, "demonstration": -0.5, "demonstrations": -0.5,
    "rally": -0.35, "rallied": -0.35, "march": -0.4, "marched": -0.4,
    "strike": -0.6, "strikes": -0.6, "walkout": -0.55, "boycott": -0.5,
    "riot": -0.9, "riots": -0.9, "clash": -0.8, "clashed": -0.8, "clashes": -0.8,
    "arrest": -0.7, "arrested": -0.7, "detain": -0.7, "detained": -0.7,
    "crackdown": -0.85, "disperse": -0.6, "dispersed": -0.6,
    "teargas": -0.85, "violence": -0.9, "violent": -0.9,
    "condemn": -0.4, "condemned": -0.4, "accuse": -0.35, "accused": -0.35,
    "threaten": -0.6, "threatened": -0.6, "warn": -0.3, "warned": -0.3,
    "reject": -0.4, "rejected": -0.4, "resign": -0.5, "resigned": -0.5,
    "curfew": -0.7, "shutdown": -0.6, "ban": -0.55, "banned": -0.55,
    "layoff": -0.5, "layoffs": -0.5, "unrest": -0.8, "escalate": -0.7,
    "escalated": -0.7, "mobilise": -0.5, "mobilize": -0.5, "mobilised": -0.5,
    "petition": -0.25, "grievance": -0.4, "outrage": -0.6, "anger": -0.5,
    # cooperative / de-escalatory
    "negotiate": 0.5, "negotiated": 0.5, "talks": 0.45, "agree": 0.6,
    "agreed": 0.6, "agreement": 0.6, "deal": 0.5, "settle": 0.6,
    "settled": 0.6, "resolve": 0.55, "resolved": 0.55, "concede": 0.4,
    "conceded": 0.4, "apologise": 0.35, "apologize": 0.35, "pledge": 0.4,
    "pledged": 0.4, "fund": 0.3, "funded": 0.3, "reopen": 0.45,
    "reinstate": 0.5, "reinstated": 0.5, "praise": 0.4, "praised": 0.4,
    "meet": 0.3, "met": 0.3, "sign": 0.45, "signed": 0.45,
}

_ACTOR_HINTS = (
    "union", "unions", "workers", "students", "teachers", "drivers", "farmers",
    "activists", "protesters", "demonstrators", "opposition", "party",
    "government", "police", "ministry", "minister", "president", "mayor",
    "council", "court", "company", "employees", "residents", "doctors",
    "nurses", "miners", "association", "federation", "coalition", "authority",
)

_TIME_PAT = re.compile(
    r"\b(today|tomorrow|yesterday|tonight|next\s+\w+|last\s+\w+|this\s+\w+|"
    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"in\s+\w+\s+days?|within\s+\w+\s+(?:days?|weeks?))\b",
    re.IGNORECASE,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


class EventExtractor(Protocol):
    """Anything that turns text into structured event tuples."""

    def extract(self, text: str) -> list[Event]: ...

    def extract_batch(self, texts: Sequence[str]) -> list[list[Event]]: ...


class RuleExtractor:
    """Deterministic offline extractor.

    Not state of the art on its own -- that is the point. It is the control
    condition against which the LLM extractor is measured, so any claimed gain
    from the LLM is attributable rather than assumed.
    """

    name = "rule"

    def __init__(self, lexicon: dict[str, float] | None = None) -> None:
        self.lexicon = dict(lexicon or _ACTION_LEXICON)

    def extract(self, text: str) -> list[Event]:
        events: list[Event] = []
        for sentence in _SENT_SPLIT.split(text.strip()):
            if not sentence:
                continue
            tokens = _WORD.findall(sentence)
            lowered = [t.lower() for t in tokens]
            hits = [(i, t) for i, t in enumerate(lowered) if t in self.lexicon]
            if not hits:
                continue
            # Strongest-magnitude action anchors the sentence's event.
            idx, action = max(hits, key=lambda p: abs(self.lexicon[p[1]]))
            actor = self._nearest_actor(lowered, tokens, idx, before=True)
            target = self._nearest_actor(lowered, tokens, idx, before=False)
            time_ref = ""
            m = _TIME_PAT.search(sentence)
            if m:
                time_ref = m.group(0).strip()
            events.append(
                Event(
                    actor=actor,
                    action=action,
                    target=target,
                    time_ref=time_ref,
                    polarity=self.lexicon[action],
                    # More lexicon hits in one sentence => less ambiguity.
                    confidence=min(1.0, 0.5 + 0.15 * len(hits)),
                    quote=sentence.strip()[:240],
                )
            )
        return events

    def extract_batch(self, texts: Sequence[str]) -> list[list[Event]]:
        return [self.extract(t) for t in texts]

    @staticmethod
    def _nearest_actor(
        lowered: list[str], tokens: list[str], idx: int, *, before: bool
    ) -> str:
        span = range(idx - 1, -1, -1) if before else range(idx + 1, len(lowered))
        for j in span:
            if lowered[j] in _ACTOR_HINTS:
                return lowered[j]
        # Fall back to a capitalised token, which usually names a real entity.
        for j in span:
            if tokens[j][:1].isupper():
                return tokens[j]
        return ""


_LLM_SYSTEM = """You extract structured event tuples from news text.

Return ONLY a JSON array. Each element must have exactly these keys:
  actor      - who acts (short noun phrase, lowercase, "" if unclear)
  action     - the event predicate as a single lowercase verb lemma
  target     - who/what is acted upon (short noun phrase, lowercase, "" if unclear)
  location   - place the event occurs ("" if unstated)
  time_ref   - verbatim temporal expression ("" if unstated)
  polarity   - float in [-1,1]; negative = conflictual, positive = cooperative
  confidence - float in [0,1]
  quote      - the verbatim sentence the event was read from

Extract only events actually asserted in the text. Do not infer, forecast, or
add events. Return [] if the text asserts no events."""


class LLMExtractor:
    """Schema-constrained LLM extraction with graceful degradation.

    If the ``anthropic`` package or an API key is missing, or a call fails,
    extraction falls back to ``RuleExtractor`` for that item and the failure is
    counted in :attr:`n_fallback`. That keeps a long backtest from dying on a
    transient error while still reporting how much of the run was actually LLM
    generated -- a silent fallback would invalidate the comparison.
    """

    name = "llm"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        max_tokens: int = 2048,
        fallback: EventExtractor | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.fallback = fallback or RuleExtractor()
        self.n_calls = 0
        self.n_fallback = 0
        self._client = None
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if key:
            try:  # pragma: no cover - depends on optional dependency
                import anthropic

                self._client = anthropic.Anthropic(api_key=key)
            except ImportError:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def extract(self, text: str) -> list[Event]:
        if self._client is None:
            self.n_fallback += 1
            return self.fallback.extract(text)
        try:  # pragma: no cover - network path
            self.n_calls += 1
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=_LLM_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            payload = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )
            return self._parse(payload)
        except Exception:
            self.n_fallback += 1
            return self.fallback.extract(text)

    def extract_batch(self, texts: Sequence[str]) -> list[list[Event]]:
        return [self.extract(t) for t in texts]

    @staticmethod
    def _parse(payload: str) -> list[Event]:
        start, end = payload.find("["), payload.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            rows = json.loads(payload[start : end + 1])
        except json.JSONDecodeError:
            return []
        events: list[Event] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("action"):
                continue
            events.append(
                Event(
                    actor=str(row.get("actor", "")).lower()[:64],
                    action=str(row["action"]).lower()[:64],
                    target=str(row.get("target", "")).lower()[:64],
                    location=str(row.get("location", ""))[:64],
                    time_ref=str(row.get("time_ref", ""))[:64],
                    polarity=_clamp(row.get("polarity", 0.0), -1.0, 1.0),
                    confidence=_clamp(row.get("confidence", 1.0), 0.0, 1.0),
                    quote=str(row.get("quote", ""))[:240],
                )
            )
        return events


def _clamp(value: object, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def annotate(documents: Iterable[Document], extractor: EventExtractor) -> list[Document]:
    """Populate ``doc.events`` in place and return the documents."""
    docs = list(documents)
    for doc, events in zip(docs, extractor.extract_batch([d.text for d in docs])):
        doc.events = events
    return docs


def get_extractor(kind: str = "auto", **kwargs) -> EventExtractor:
    """``"rule"``, ``"llm"``, or ``"auto"`` (LLM when a key is present)."""
    if kind == "rule":
        return RuleExtractor()
    if kind == "llm":
        return LLMExtractor(**kwargs)
    if kind == "auto":
        llm = LLMExtractor(**kwargs)
        return llm if llm.available else RuleExtractor()
    raise ValueError(f"unknown extractor kind: {kind!r}")
