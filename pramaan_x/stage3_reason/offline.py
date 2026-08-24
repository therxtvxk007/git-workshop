"""Deterministic offline responder.

Produces schema-valid JSON from the evidence block embedded in the prompt. It
reads the structured `EVIDENCE:` and `TARGET:` sections that `prompts.py` emits,
so its answers track the actual inputs rather than being constant -- which is
what makes it useful for testing the cascade's control flow.

It is explicitly not a language model and its `plausibility` is a monotone
function of evidence volume and recency, nothing more.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

_TARGET = re.compile(r"^TARGET:\s*(?P<loc>[^|]+)\|(?P<et>\S+)", re.MULTILINE)
_HORIZON = re.compile(r"^HORIZON_DAYS:\s*(\d+)", re.MULTILINE)
_EVIDENCE = re.compile(r"^\s*-\s*\[(?P<doc>[^\]]+)\]\s*(?P<text>.+)$", re.MULTILINE)
_SPANS = re.compile(r"^\s*-\s*\[[^\]]+\]\s*(.+)$", re.MULTILINE)


def respond(prompt: str, schema: type[BaseModel] | None, index: int, seed: int) -> str:
    name = schema.__name__ if schema else ""
    ev = _EVIDENCE.findall(prompt)
    m = _TARGET.search(prompt)
    location = m.group("loc").strip() if m else "unknown"
    event_type = m.group("et").strip() if m else "unknown"
    hz = _HORIZON.search(prompt)
    horizon = int(hz.group(1)) if hz else 7

    # Evidence volume drives confidence, saturating -- more copies of the same
    # story must not push this toward certainty.
    n = len(ev)
    conf = round(min(0.15 + 0.12 * n, 0.88), 4)

    if name == "HypothesisSet":
        # `index` diversifies across SCATTER samples without randomness, so a
        # rerun produces byte-identical output.
        variants = [(event_type, horizon), (event_type, max(horizon // 2, 1)),
                    (event_type, min(horizon * 2, 365))]
        et, h = variants[index % len(variants)]
        return json.dumps({"hypotheses": [{
            "location": location, "event_type": et, "horizon_days": h,
            "plausibility": round(max(conf - 0.05 * index, 0.05), 4),
            "rationale": _rationale(ev, location, et),
            "supporting_doc_ids": [d for d, _ in ev][:8],
        }]})

    if name == "Verdict":
        verdict = "supports" if n >= 2 else ("insufficient" if n == 0 else "contradicts")
        return json.dumps({
            "supported": verdict, "confidence": conf,
            "chosen_event_type": event_type if verdict == "supports" else None,
            "reasoning": _rationale(ev, location, event_type),
            "contradicting_doc_ids": [d for d, _ in ev][-1:] if verdict == "contradicts" else [],
        })

    if name == "ExtractionBatch":
        events: list[dict[str, Any]] = []
        for _doc, text in ev[:8]:
            events.append({
                "subject": location, "relation": "reported",
                "object": " ".join(text.split()[:6]) or "unspecified",
                "event_type": event_type, "event_time": None, "location": location,
                "extractor_confidence": conf,
                "supporting_span": text.strip()[:300] or "no span available",
            })
        return json.dumps({"events": events})

    return json.dumps({"note": "offline backend", "evidence_count": n})


def _rationale(ev: list[tuple[str, str]], location: str, event_type: str) -> str:
    if not ev:
        return (f"No retrieved evidence for {event_type} at {location}; the offline "
                f"responder has no basis to assert a change in risk.")
    heads = "; ".join(t.strip()[:70] for _, t in ev[:3])
    return (f"{len(ev)} retrieved item(s) bearing on {event_type} at {location}. "
            f"Leading spans: {heads}.")
