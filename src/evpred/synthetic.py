"""A generative simulator for text-based event forecasting.

Why a simulator is part of the system, not a toy
------------------------------------------------
The survey's gap G6 is that models "need to be validated with actually occurred
events", and G10 that validation is under-resourced. Real corpora (GDELT, ICEWS,
ACLED) are the right end goal and ``adapters.py`` targets them -- but they give
you no ground truth about *which article* was a genuine precursor, only whether
the event happened. That makes it impossible to tell a model that found the real
escalation signature from one that latched onto a spurious correlate.

This simulator has a known latent process, so it supports three things real data
cannot:

* a **signal ceiling** -- the Bayes-optimal score given the latent state, so
  "0.78 AUC" can be read against what is achievable rather than in a vacuum;
* **labelled precursors** -- each document knows whether it was generated from
  the escalation process, so precursor recovery is measurable (see
  ``precursor_recall`` in the demo);
* **controllable difficulty** -- distractor rate, noise, and regime strength are
  knobs, so failure modes can be reproduced deterministically.

The text is template-generated and is NOT a substitute for real news. Numbers
from this simulator validate that the *pipeline* works; they say nothing about
real-world accuracy. See ``docs/04-limitations.md``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

import numpy as np

from .schema import Date, Document

_ESCALATION_TEMPLATES = [
    "The {actor} warned of a {noun} after talks with the {counter} collapsed on {day}.",
    "Members of the {actor} voted to strike, threatening a walkout across {place} {day}.",
    "Police detained {n} demonstrators in {place} as the {actor} marched toward the ministry.",
    "The {actor} rejected the latest offer and accused the {counter} of bad faith.",
    "Anger grew in {place} after the {counter} announced layoffs affecting {n} workers.",
    "A crackdown on the {actor} in {place} drew condemnation from the opposition.",
    "The {actor} called for a mass rally in {place}, escalating a dispute with the {counter}.",
    "Clashes broke out in {place} when officers dispersed a protest by the {actor}.",
    "The {counter} imposed a curfew in {place} following unrest over the {noun}.",
    "Union leaders said a general strike in {place} was likely {day} absent concessions.",
]

_DEESCALATION_TEMPLATES = [
    "The {actor} and the {counter} agreed to resume negotiations in {place}.",
    "A deal was signed in {place}, settling a long dispute over the {noun}.",
    "The {counter} pledged funding for {place} after meeting the {actor}.",
    "Officials praised the {actor} for reopening talks in {place}.",
    "The {counter} conceded on pay, and the {actor} suspended planned action.",
]

_BACKGROUND_TEMPLATES = [
    "Rainfall in {place} was above the seasonal average, the weather service said.",
    "The {Place} football club appointed a new manager ahead of the season.",
    "A new commuter line opened in {place}, cutting journey times by {n} minutes.",
    "Retail sales in {place} rose modestly, according to a quarterly survey.",
    "The {Place} museum announced a summer exhibition of regional photography.",
    "Local growers in {place} reported a strong harvest this year.",
    "A technology firm said it would open an office in {place}, adding {n} jobs.",
    "The {Place} marathon drew record participation over the weekend.",
]

_ACTORS = ["teachers union", "transport workers union", "students association",
           "miners federation", "nurses association", "farmers coalition",
           "drivers syndicate", "civil servants union"]
_COUNTERS = ["government", "ministry", "city council", "company", "regional authority"]
_NOUNS = ["pay dispute", "pension reform", "fuel price rise", "contract terms",
          "hiring freeze", "subsidy cut"]
_DAYS = ["today", "tomorrow", "next week", "on Friday", "on Monday", "this weekend"]
_SOURCES = ["national-wire", "regional-daily", "broadcast", "aggregator", "local-blog"]


@dataclass(slots=True)
class SimConfig:
    n_regions: int = 8
    n_days: int = 420
    start: Date = _dt.date(2024, 1, 1)
    base_docs_per_day: float = 2.5
    tension_doc_gain: float = 7.0
    persistence: float = 0.86
    shock_rate: float = 0.055
    shock_scale: float = 0.5
    event_gain: float = 0.16
    event_floor: float = 0.004
    distractor_ratio: float = 0.55
    """Share of documents drawn from background templates regardless of state."""
    label_noise: float = 0.02
    horizon_days: int = 7
    seed: int = 0


class EventSimulator:
    """Latent-tension simulator producing documents and ground-truth events."""

    def __init__(self, config: SimConfig | None = None) -> None:
        self.config = config or SimConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.regions = [f"region-{i:02d}" for i in range(self.config.n_regions)]
        self.tension: dict[str, np.ndarray] = {}
        self.events: dict[tuple[str, Date], int] = {}

    # -- latent process --------------------------------------------------

    def _simulate_tension(self) -> None:
        cfg = self.config
        for region in self.regions:
            x = np.zeros(cfg.n_days, dtype=np.float64)
            level = float(self.rng.uniform(0.02, 0.12))
            for t in range(cfg.n_days):
                shock = 0.0
                if self.rng.random() < cfg.shock_rate:
                    shock = abs(self.rng.normal(0.0, cfg.shock_scale))
                level = cfg.persistence * level + shock
                level = float(np.clip(level + self.rng.normal(0.0, 0.015), 0.0, 1.5))
                x[t] = level
            self.tension[region] = x

    def _simulate_events(self) -> None:
        cfg = self.config
        for region in self.regions:
            x = self.tension[region]
            for t in range(cfg.n_days):
                p = min(0.9, cfg.event_floor + cfg.event_gain * x[t])
                if self.rng.random() < p:
                    self.events[(region, self._date(t))] = 1

    def _date(self, t: int) -> Date:
        return self.config.start + _dt.timedelta(days=int(t))

    # -- text generation -------------------------------------------------

    def _render(self, template: str) -> str:
        return template.format(
            actor=self.rng.choice(_ACTORS),
            counter=self.rng.choice(_COUNTERS),
            noun=self.rng.choice(_NOUNS),
            place=self.rng.choice(["the capital", "the port district", "the north",
                                   "downtown", "the industrial zone"]),
            Place=self.rng.choice(["the capital", "the port district", "the north",
                                   "downtown", "the industrial zone"]).replace("the ", ""),
            day=self.rng.choice(_DAYS),
            n=int(self.rng.integers(3, 400)),
        )

    def _make_document(self, region: str, date: Date, idx: int, tension: float) -> Document:
        cfg = self.config
        # Probability this document reflects the latent escalation process.
        p_escalation = float(np.clip(tension / (tension + 0.6), 0.0, 0.95))
        p_escalation *= 1.0 - cfg.distractor_ratio

        roll = self.rng.random()
        if roll < p_escalation:
            template, kind = self.rng.choice(_ESCALATION_TEMPLATES), "escalation"
        elif roll < p_escalation + 0.08:
            template, kind = self.rng.choice(_DEESCALATION_TEMPLATES), "deescalation"
        else:
            template, kind = self.rng.choice(_BACKGROUND_TEMPLATES), "background"

        # Two to three sentences per article, the first carrying the signal.
        body = [self._render(template)]
        for _ in range(int(self.rng.integers(1, 3))):
            body.append(self._render(self.rng.choice(_BACKGROUND_TEMPLATES)))

        return Document(
            doc_id=f"{region}:{date.isoformat()}:{idx}",
            text=" ".join(body),
            date=date,
            region=region,
            source=str(self.rng.choice(_SOURCES)),
            meta={"kind": kind, "is_precursor": kind == "escalation",
                  "latent_tension": float(tension)},
        )

    # -- public API ------------------------------------------------------

    def generate(self) -> tuple[list[Document], dict[tuple[str, Date], int]]:
        cfg = self.config
        self._simulate_tension()
        self._simulate_events()
        documents: list[Document] = []
        for region in self.regions:
            x = self.tension[region]
            for t in range(cfg.n_days):
                rate = cfg.base_docs_per_day + cfg.tension_doc_gain * x[t]
                n_docs = int(self.rng.poisson(rate))
                date = self._date(t)
                for i in range(n_docs):
                    documents.append(self._make_document(region, date, i, float(x[t])))
        return documents, dict(self.events)

    def horizon_labels(self, horizon_days: int | None = None) -> dict[tuple[str, Date], int]:
        """Label for ``(region, origin)``: did an event occur in the horizon window?"""
        cfg = self.config
        h = horizon_days or cfg.horizon_days
        labels: dict[tuple[str, Date], int] = {}
        for region in self.regions:
            for t in range(cfg.n_days):
                origin = self._date(t)
                hit = any(
                    (region, origin + _dt.timedelta(days=k)) in self.events
                    for k in range(h)
                )
                y = int(hit)
                if self.rng.random() < cfg.label_noise:
                    y = 1 - y
                labels[(region, origin)] = y
        return labels

    def oracle_scores(self, origins: list[Date], regions: list[str],
                      horizon_days: int) -> np.ndarray:
        """Bayes-optimal probability given the *latent* state.

        This is the ceiling any text-based model is chasing. Reporting a model's
        AUC next to the oracle's is far more informative than reporting it alone.
        """
        cfg = self.config
        out = []
        for region in regions:
            x = self.tension[region]
            for origin in origins:
                t = (origin - cfg.start).days
                p_none = 1.0
                for k in range(horizon_days):
                    if 0 <= t + k < cfg.n_days:
                        p_none *= 1.0 - min(0.9, cfg.event_floor + cfg.event_gain * x[t + k])
                out.append(1.0 - p_none)
        return np.array(out, dtype=np.float64)


def make_dataset(config: SimConfig | None = None):
    """Convenience wrapper returning ``(simulator, documents, labels)``."""
    sim = EventSimulator(config)
    documents, _ = sim.generate()
    labels = sim.horizon_labels()
    return sim, documents, labels
