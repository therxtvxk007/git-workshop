"""Operating-point selection, on the selection window and nowhere else.

The defect this module was written for: the protocol declared a calibration
window and then nothing used it. Every width, threshold and variant in the
config was a value somebody typed, and the only quality threshold in the suite
-- a Recall@100 floor -- was asserted against the *locked test window*. So the
test window did select something after all: whether a change was allowed to
merge.

The repair is not to delete the floor. A retrieval system with no regression
tripwire is worse off. The repair is to move every choice onto data that is
allowed to inform choices, and to make it impossible to accidentally choose on
the locked window:

  * `select_operating_point` refuses any window the protocol does not mark
    selectable, so passing `"test"` raises rather than quietly working;
  * every candidate, its score and the objective are recorded in the artefact,
    so a reader can see the search rather than only its winner;
  * CI floors are measured on the `regression` window, which is distinct from
    the `selection` window the parameters were tuned on and distinct from the
    locked test window a build must never be graded against.

The search is a coordinate sweep rather than a full cross product. That is a
cost decision and it is stated in the artefact: a coordinate sweep from a fixed
starting point is not a global search and should not be described as one.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..config import Stage2Config
from .metrics import evaluate_retrieval
from .oracle_target_retrieval import OracleTargetQuery
from .protocol import TemporalProtocol

#: The candidate grid. Fixed here, before any measurement, and recorded whole
#: in every artefact so the winner can be read against what it beat.
CANDIDATE_GRID: dict[str, tuple[Any, ...]] = {
    "late_top_k": (40, 60, 100),
    "rerank_top_k": (10, 20, 40),
    "rrf_k": (30, 60, 120),
}

#: What the search maximises. Named in the artefact because "the best
#: configuration" means nothing without it.
OBJECTIVE = "ndcg@10"

SEARCH_STRATEGY = (
    "coordinate sweep over CANDIDATE_GRID from the config defaults, one "
    "parameter at a time in declaration order, keeping each improvement. Not a "
    "full cross product and not a global optimum."
)


class SelectionError(RuntimeError):
    """Raised when a selection would read data it is not allowed to read."""


@dataclass
class Candidate:
    """One configuration and what it scored on the selection window."""

    params: dict[str, Any]
    score: float
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"params": dict(self.params), "score": self.score, "metrics": dict(self.metrics)}


@dataclass
class SelectionResult:
    """The chosen operating point and the whole search that produced it."""

    window: str
    objective: str
    strategy: str
    grid: dict[str, list[Any]]
    selected: dict[str, Any]
    baseline: dict[str, Any]
    candidates: list[Candidate]
    n_queries: int
    improvement: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "objective": self.objective,
            "strategy": self.strategy,
            "grid": {k: list(v) for k, v in self.grid.items()},
            "selected": dict(self.selected),
            "baseline": dict(self.baseline),
            "improvement": self.improvement,
            "n_selection_queries": self.n_queries,
            "n_candidates_evaluated": len(self.candidates),
            "candidates": [c.to_dict() for c in self.candidates],
            "fingerprint": self.fingerprint(),
        }

    def fingerprint(self) -> str:
        blob = json.dumps(
            {
                "grid": {k: list(v) for k, v in self.grid.items()},
                "objective": self.objective,
                "selected": self.selected,
                "window": self.window,
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def apply(self, cfg: Stage2Config) -> Stage2Config:
        return dataclasses.replace(cfg, **self.selected)


def assert_selection_inputs(
    protocol: TemporalProtocol, window: str, queries: Sequence[OracleTargetQuery]
) -> None:
    """Refuse to select on anything but a selectable window.

    Two checks, because either alone is bypassable: the window has to be one
    the protocol permits, *and* every query handed over has to actually fall in
    it. A caller who passes test-window queries with `window="selection"` is
    caught by the second.
    """
    protocol.assert_selection_window(window)
    stray = [q.query_id for q in queries if not protocol.contains(window, q.event_time)]
    if stray:
        raise SelectionError(
            f"{len(stray)} queries handed to the selector do not lie in the "
            f"{window!r} window (first: {stray[:3]}). Selecting on data from "
            f"outside the selection window is how a locked test window stops "
            f"being locked."
        )


def select_operating_point(
    protocol: TemporalProtocol,
    queries: Sequence[OracleTargetQuery],
    evaluate: Callable[[Stage2Config, Sequence[OracleTargetQuery]], dict[str, float]],
    *,
    base: Stage2Config,
    window: str = "selection",
    grid: dict[str, tuple[Any, ...]] | None = None,
    objective: str = OBJECTIVE,
) -> SelectionResult:
    """Choose widths on the selection window.

    `evaluate` takes a candidate config and the selection queries and returns a
    metric dict. It is injected rather than imported so this module cannot
    reach for a corpus, a test query or anything else it has no business
    touching.
    """
    assert_selection_inputs(protocol, window, queries)
    grid = grid or CANDIDATE_GRID
    if not queries:
        raise SelectionError(
            f"the {window!r} window produced no queries, so nothing can be "
            "selected on it. Widen the window or lengthen the corpus rather "
            "than falling back to the test window."
        )

    baseline_params = {k: getattr(base, k) for k in grid}
    baseline_metrics = evaluate(base, queries)
    baseline_score = float(baseline_metrics.get(objective, float("nan")))
    candidates = [Candidate(dict(baseline_params), baseline_score, baseline_metrics)]

    best_params = dict(baseline_params)
    best_score = baseline_score
    for name, values in grid.items():
        for value in values:
            if value == best_params[name]:
                continue
            params = {**best_params, name: value}
            metrics = evaluate(dataclasses.replace(base, **params), queries)
            score = float(metrics.get(objective, float("nan")))
            candidates.append(Candidate(dict(params), score, metrics))
            if score > best_score:
                best_score, best_params = score, params

    return SelectionResult(
        window=window,
        objective=objective,
        strategy=SEARCH_STRATEGY,
        grid={k: list(v) for k, v in grid.items()},
        selected=best_params,
        baseline=baseline_params,
        candidates=candidates,
        n_queries=len(queries),
        improvement=float(best_score - baseline_score),
    )


def measure_regression_floor(
    protocol: TemporalProtocol,
    queries: Sequence[OracleTargetQuery],
    evaluate: Callable[[Stage2Config, Sequence[OracleTargetQuery]], dict[str, float]],
    *,
    cfg: Stage2Config,
    window: str = "regression",
    margin: float = 0.15,
    metrics: Sequence[str] = ("recall@100", "ndcg@10", "mrr"),
) -> dict[str, Any]:
    """Measure CI quality floors on the regression window.

    The floor sits `margin` below the measured value: a tripwire for a code
    change that breaks retrieval, not an estimate of quality. It is measured on
    a window the parameters were *not* tuned on, and on no account on the test
    window -- a build that fails on the locked window has graded itself against
    the thing it is supposed to only report.
    """
    assert_selection_inputs(protocol, window, queries)
    if not queries:
        raise SelectionError(f"the {window!r} window produced no queries")
    measured = evaluate(cfg, queries)
    return {
        "window": window,
        "margin": margin,
        "n_queries": len(queries),
        "measured": {m: float(measured.get(m, float("nan"))) for m in metrics},
        "floor": {m: float(measured.get(m, 0.0)) * (1.0 - margin) for m in metrics},
        "note": (
            "Floors are tripwires measured on the regression window, which is "
            "distinct from the selection window the parameters were tuned on "
            "and from the locked test window. No CI decision reads a test-window "
            "metric."
        ),
    }


def evaluator(
    corpus: Sequence[Any],
    provider_factory: Callable[[], Any],
    *,
    ks: Sequence[int] = (10, 20, 50, 100),
    top_k: int = 200,
) -> Callable[[Stage2Config, Sequence[OracleTargetQuery]], dict[str, float]]:
    """Build the `evaluate` callable the selector needs.

    The provider is built once and reused across candidates, and each candidate
    gets a `with_config` view of the already-fitted cascade. Refitting per
    candidate would be slow and would risk fitting something subtly different,
    which is exactly the class of mistake this package exists to prevent.
    """
    provider = provider_factory()

    def evaluate(cfg: Stage2Config, queries: Sequence[OracleTargetQuery]) -> dict[str, float]:
        runs: list[tuple[list[str], set[str]]] = []
        for q in queries:
            cascade = provider.for_origin(q.origin).with_config(cfg)
            evidence, _ = cascade.retrieve(
                q.text, as_of=q.origin, top_k=top_k, allowed=provider.allowed_at(q.origin)
            )
            runs.append(([e.doc_id for e in evidence], set(q.relevant)))
        report = evaluate_retrieval(runs, ks=ks)
        out = {f"recall@{k}": v for k, v in report.recall.items()}
        out |= {f"ndcg@{k}": v for k, v in report.ndcg.items()}
        out["mrr"] = report.mrr
        return out

    return evaluate
