"""Stage 1: the cheap high-recall scan, and the gate it feeds.

Every detector here runs over every surviving document. That is affordable
because none of them is a large model -- the entire stage is BM25, a learned
lexicon, gradient boosting over ten tabular features, and two sequential
detectors over daily counts.

The gate takes the *union* of detectors, never the intersection. Intersecting
detectors is the standard way to make a stage-1 filter look precise while
quietly destroying the recall the rest of the cascade depends on: a document
that only one detector notices is exactly the document worth keeping.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from ..config import Stage1Config
from ..types import Document, EventTuple
from .bm25 import BM25Index
from .burst import burst_features
from .embed import Embedder, build_embedder
from .extract import RuleExtractor, consensus
from .lexical import LexicalIndicators
from .relevance import RelevanceModel, cheap_features


@dataclass
class Stage1Result:
    retained: list[Document]
    tuples: list[EventTuple]
    fired: dict[str, set[str]]                  # detector -> doc_ids
    scores: dict[str, np.ndarray] = field(default_factory=dict)
    embeddings: np.ndarray | None = None
    doc_order: list[str] = field(default_factory=list)
    burst: dict[str, dict[str, float]] = field(default_factory=dict)
    elapsed_s: float = 0.0
    n_input: int = 0

    @property
    def retention(self) -> float:
        return len(self.retained) / self.n_input if self.n_input else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "input": self.n_input,
            "retained": len(self.retained),
            "retention": round(self.retention, 4),
            "tuples": len(self.tuples),
            "fired_by_detector": {k: len(v) for k, v in self.fired.items()},
            "unique_contribution": self.unique_contribution(),
            "elapsed_s": round(self.elapsed_s, 2),
        }

    def unique_contribution(self) -> dict[str, int]:
        """Documents each detector is *solely* responsible for retaining.

        This is the number that justifies a detector's existence. A detector
        whose unique contribution is zero is pure cost and should be dropped.
        """
        counts: dict[str, int] = {}
        for name, ids in self.fired.items():
            others: set[str] = set()
            for other, oids in self.fired.items():
                if other != name:
                    others |= oids
            counts[name] = len(ids - others)
        return counts


class Stage1Scanner:
    def __init__(
        self,
        cfg: Stage1Config | None = None,
        *,
        gazetteer: set[str] | None = None,
        event_types: Sequence[str] = (),
        source_reliability: dict[str, float] | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.cfg = cfg or Stage1Config()
        self.gazetteer = gazetteer or set()
        self.event_types = tuple(event_types)
        self.source_reliability = source_reliability or {}
        self.lexicon = LexicalIndicators()
        self.relevance = RelevanceModel(threshold=self.cfg.relevance_threshold,
                                        target_recall=self.cfg.relevance_target_recall)
        self.embedder = embedder or build_embedder(self.cfg.embedder, self.cfg.embed_dim)
        self.extractor = RuleExtractor(
            gazetteer=self.gazetteer, lexicon=self.lexicon,
            event_types=self.event_types, source_reliability=self.source_reliability,
            min_type_score=self.cfg.extractor_min_type_score,
        )
        self.fitted = False
        self._lexical_cut: float = 0.0
        self._burst_lex_cut: float = 0.0

    # ------------------------------------------------------------- fit ---

    def fit(
        self,
        docs: Sequence[Document],
        labels: Sequence[int],
        *,
        event_types_per_doc: Sequence[str] | None = None,
        holdout: float = 0.25,
        seed: int = 20260824,
    ) -> Stage1Scanner:
        """Fit lexicon and relevance model on a *training window only*.

        `docs` must already be restricted to the training period by the caller.
        Nothing in here re-checks that, because the temporal split is a property
        of the evaluation protocol, not of this class -- see eval/protocol.py.
        """
        texts = [d.full_text for d in docs]
        self.lexicon.fit(texts, labels, event_types=event_types_per_doc)
        self.extractor.lexicon = self.lexicon

        if hasattr(self.embedder, "fit"):
            self.embedder.fit(texts)

        X = np.vstack([
            cheap_features(d, self.lexicon, self.event_types,
                           self.source_reliability, self.gazetteer)
            for d in docs
        ])
        y = np.asarray(labels).astype(int)

        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(docs))
        n_hold = max(1, int(holdout * len(docs)))
        hold, train = idx[:n_hold], idx[n_hold:]
        self.relevance.fit(X[train], y[train], seed=seed)
        self.relevance.calibrate_threshold(X[hold], y[hold])

        # Lexical trigger: a percentile of the training distribution, so the
        # gate adapts to corpus verbosity instead of using a magic constant.
        lex = self.lexicon.score_all(texts)
        self._lexical_cut = float(np.quantile(lex, self.cfg.lexical_trigger_percentile))
        self._burst_lex_cut = float(np.quantile(lex, self.cfg.burst_lexical_percentile))
        self.fitted = True
        return self

    # ------------------------------------------------------------ scan ---

    def scan(
        self,
        docs: Sequence[Document],
        *,
        origin: datetime | None = None,
        history_days: int = 120,
    ) -> Stage1Result:
        if not self.fitted:
            raise RuntimeError("Stage1Scanner.fit must be called before scan")
        t0 = time.perf_counter()
        docs = list(docs)
        ids = [d.doc_id for d in docs]
        texts = [d.full_text for d in docs]
        fired: dict[str, set[str]] = defaultdict(set)

        # -- detector 1: lexical weight -----------------------------------
        lex = self.lexicon.score_all(texts)
        for i, v in enumerate(lex):
            if v >= self._lexical_cut:
                fired["lexical"].add(ids[i])

        # -- detector 2: BM25 against learned per-type queries -------------
        bm = BM25Index(k1=self.cfg.bm25_k1, b=self.cfg.bm25_b).fit(ids, texts)
        bm25_best = np.zeros(len(docs))
        for et in self.event_types:
            q = self.lexicon.query_for(et, n=20)
            if not q:
                continue
            s = bm.score(q)
            bm25_best = np.maximum(bm25_best, s)
        if bm25_best.max() > 0:
            cut = float(np.quantile(bm25_best[bm25_best > 0], 0.5))
            for i, v in enumerate(bm25_best):
                if v >= cut and v > 0:
                    fired["bm25"].add(ids[i])

        # -- detector 3: relevance model -----------------------------------
        X = np.vstack([
            cheap_features(d, self.lexicon, self.event_types,
                           self.source_reliability, self.gazetteer)
            for d in docs
        ])
        p_rel = self.relevance.predict_proba(X)
        for i, v in enumerate(p_rel):
            if v >= self.relevance.threshold:
                fired["relevance"].add(ids[i])

        # -- detector 4: extraction ----------------------------------------
        tuples = consensus([self.extractor.extract(docs, origin=origin)])
        for t in tuples:
            fired["extraction"].add(t.doc_id)

        # -- detector 5: temporal burst / change point ---------------------
        burst = self._burst_by_location(docs, history_days=history_days)
        hot = {loc for loc, f in burst.items()
               if f["cusum_fired"] > 0 or f["days_since_changepoint"] in range(15)}
        if hot:
            for i, d in enumerate(docs):
                if self._doc_location(d) not in hot:
                    continue
                if self.cfg.burst_requires_lexical and lex[i] < self._burst_lex_cut:
                    continue
                fired["burst"].add(d.doc_id)

        # -- union ----------------------------------------------------------
        retained_ids: set[str] = set()
        if self.cfg.retain_on_any:
            for s in fired.values():
                retained_ids |= s
        else:
            sets = list(fired.values())
            retained_ids = set.intersection(*sets) if sets else set()

        retained = [d for d in docs if d.doc_id in retained_ids]
        emb = self.embedder.encode([d.full_text for d in retained]) if retained else None

        return Stage1Result(
            retained=retained,
            tuples=[t for t in tuples if t.doc_id in retained_ids],
            fired=dict(fired),
            scores={"lexical": lex, "bm25": bm25_best, "relevance": p_rel},
            embeddings=emb,
            doc_order=[d.doc_id for d in retained],
            burst=burst,
            elapsed_s=time.perf_counter() - t0,
            n_input=len(docs),
        )

    # --------------------------------------------------------- helpers ---

    def _doc_location(self, doc: Document) -> str:
        text = doc.full_text.lower()
        for g in self.gazetteer:
            if g.lower() in text:
                return g
        return "unknown"

    def _burst_by_location(self, docs: Sequence[Document], *, history_days: int
                           ) -> dict[str, dict[str, float]]:
        """Daily document counts per location, then both change detectors.

        Counts are over *canonical* documents only. Running this over the raw
        stream would make a syndication spike look like a burst of activity,
        which is the exact confusion stage 0 exists to prevent.
        """
        if not docs:
            return {}
        end = max(d.published_at for d in docs)
        start = end - timedelta(days=history_days)
        per_loc: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for d in docs:
            if d.published_at < start:
                continue
            day = (d.published_at - start).days
            per_loc[self._doc_location(d)][day] += 1

        out: dict[str, dict[str, float]] = {}
        for loc, days in per_loc.items():
            series = np.zeros(history_days + 1)
            for day, n in days.items():
                if 0 <= day < series.size:
                    series[day] = n
            out[loc] = burst_features(
                series, k=self.cfg.burst_cusum_k, h=self.cfg.burst_cusum_h,
                hazard=self.cfg.bocpd_hazard, threshold=self.cfg.bocpd_threshold,
            )
        return out
