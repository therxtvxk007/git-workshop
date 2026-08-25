"""Selection happens on the selection window. The locked test window reports.

The defect these tests were written against: the protocol declared a
calibration window that nothing used, every width in the config was a value
somebody typed, and the only quality threshold in the suite -- a Recall@100
floor in `test_retrieval.py` -- was asserted against the *locked test window*.
So the test window did select something: whether a change was allowed to merge.
A window that decides what merges is not a locked window.

Every test below is either a control that fails on the committed
implementation, or a guard against the specific way the property could be
restored to being prose.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from pramaan_x.config import Config
from pramaan_x.eval.harness import prepare, run_method
from pramaan_x.eval.oracle_target_retrieval import (
    STRICT,
    build_oracle_target_queries,
)
from pramaan_x.eval.protocol import ProtocolError
from pramaan_x.eval.selection import (
    CANDIDATE_GRID,
    OBJECTIVE,
    SelectionError,
    assert_selection_inputs,
    select_operating_point,
)

ROOT = Path(__file__).resolve().parent.parent
DAYS = 420
SEED = 20260824


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config().apply_profile()


@pytest.fixture(scope="module")
def prep(cfg):
    return prepare(cfg, days=DAYS, seed=SEED, n_locations=8, n_event_types=6)


@pytest.fixture(scope="module")
def run(prep, cfg):
    return run_method(prep, cfg, STRICT, stages=("rerank",), write=False)


def _queries(prep, window):
    return build_oracle_target_queries(
        prep.ground_truth, prep.lexicon, prep.corpus, prep.protocol, window
    )


# --------------------------------------------- the test window selects nothing ---


def test_selecting_on_the_locked_test_window_is_refused(prep):
    """END-TO-END NEGATIVE CONTROL for requirement 3.

    On the committed implementation there was nothing to refuse: no selector
    existed and the floor read test metrics directly.
    """
    with pytest.raises(ProtocolError, match="may not be used to select"):
        prep.protocol.assert_selection_window("test")


def test_a_selector_handed_test_window_queries_is_rejected(prep):
    """NEGATIVE CONTROL: labelling the call `selection` must not be enough.

    A caller who passes test-window queries while claiming to select on the
    selection window is caught by the second half of the guard.
    """
    test_q = _queries(prep, "test")
    assert test_q, "no test queries to smuggle"
    with pytest.raises(SelectionError, match="do not lie in the 'selection' window"):
        assert_selection_inputs(prep.protocol, "selection", test_q)


def test_a_selector_that_reads_test_labels_cannot_run(prep, cfg):
    """NEGATIVE CONTROL: a deliberately dishonest selector.

    It maximises a score computed from test-window relevance. The guard rejects
    it before it can evaluate a single candidate, so the dishonesty is not
    merely discouraged.
    """
    test_q = _queries(prep, "test")

    def cheating_evaluate(candidate_cfg, queries):  # pragma: no cover - must not run
        raise AssertionError("the cheating selector was allowed to evaluate")

    with pytest.raises(SelectionError):
        select_operating_point(
            prep.protocol, test_q, cheating_evaluate, base=cfg.stage2, window="selection"
        )
    with pytest.raises(ProtocolError):
        select_operating_point(
            prep.protocol, test_q, cheating_evaluate, base=cfg.stage2, window="test"
        )


def test_changing_test_labels_cannot_change_a_selected_parameter(prep, cfg):
    """The property stated directly: perturb every test-window label and show
    the chosen operating point does not move."""
    import copy

    from pramaan_x.eval.harness import _choose_operating_point
    from pramaan_x.stage1_scan.embed import build_embedder
    from pramaan_x.stage2_retrieve.rerank import build_reranker

    def choose(p):
        record, _floors, chosen = _choose_operating_point(
            p,
            cfg,
            p.corpus,
            lambda: build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim),
            lambda: build_reranker(cfg.stage2.reranker),
            None,
            (10, 20, 50, 100),
            200,
        )
        return record["selected"], record["fingerprint"], chosen

    before = choose(prep)

    poisoned = copy.copy(prep)
    poisoned.ground_truth = copy.deepcopy(prep.ground_truth)
    changed = 0
    for (key, iso), docs in list(poisoned.ground_truth.precursor_docs.items()):
        when = __import__("datetime").datetime.fromisoformat(iso)
        if poisoned.protocol.contains("test", when):
            poisoned.ground_truth.precursor_docs[(key, iso)] = list(reversed(docs))[:1]
            changed += 1
    assert changed > 0, "no test-window labels were perturbed, so this proves nothing"

    after = choose(poisoned)
    assert before[0] == after[0], "a selected parameter moved when test labels changed"
    assert before[1] == after[1]
    assert dataclasses.asdict(before[2]) == dataclasses.asdict(after[2])


# ------------------------------------------------- the search is on the record ---


def test_the_artefact_records_the_grid_the_objective_and_every_candidate(run):
    sel = run.payload["extra"]["selection"]
    assert sel["window"] == "selection"
    assert sel["objective"] == OBJECTIVE
    assert sel["grid"] == {k: list(v) for k, v in CANDIDATE_GRID.items()}
    assert sel["n_selection_queries"] > 0
    assert sel["n_candidates_evaluated"] == len(sel["candidates"]) > 1
    for c in sel["candidates"]:
        assert set(c["params"]) == set(CANDIDATE_GRID)
        assert OBJECTIVE in c["metrics"]
    assert set(sel["selected"]) == set(CANDIDATE_GRID)
    assert "not a full cross product" in sel["strategy"].lower()


def test_the_selected_point_is_the_one_actually_used(run):
    sel = run.payload["extra"]["selection"]
    assert run.payload["extra"]["operating_point"] == sel["selected"]


def test_the_selected_point_is_the_best_candidate_on_the_objective(run):
    sel = run.payload["extra"]["selection"]
    best = max(sel["candidates"], key=lambda c: c["score"])
    assert best["params"] == sel["selected"]


# ---------------------------------------------------- floors live off the test ---


def test_ci_floors_are_measured_on_the_regression_window(run):
    floors = run.payload["extra"]["regression_floors"]
    assert floors["window"] == "regression"
    assert floors["n_queries"] > 0
    for metric, value in floors["floor"].items():
        assert value < floors["measured"][metric]
    assert "locked test window" in floors["note"]


def test_the_regression_window_is_disjoint_from_selection_and_test(prep):
    p = prep.protocol
    _sel_start, sel_end = p.window("selection")
    reg_start, reg_end = p.window("regression")
    assert sel_end == reg_start
    assert reg_end <= p.test_start
    assert not p.contains("selection", reg_start)
    assert not p.contains("test", reg_start)
    assert len(_queries(prep, "regression")) > 0


def test_no_test_in_the_suite_asserts_a_quality_floor_on_test_metrics():
    """NEGATIVE CONTROL, at the source level.

    The committed `test_recall_floor_at_100` compared a test-window Recall@100
    against a hard-coded number, so a build's fate depended on the locked
    window. This walks the suite's syntax tree and fails if any comparison
    against a numeric literal reads a metric off a fixture whose name marks it
    as a test-window run.
    """
    offenders: list[str] = []
    banned_sources = ("strict_run", "test_report", "test_metrics")
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not any(
                isinstance(c, ast.Constant) and isinstance(c.value, float) for c in node.comparators
            ):
                continue
            src = ast.unparse(node)
            if any(b in src for b in banned_sources) and (
                "recall" in src or "ndcg" in src or "mrr" in src or "precision" in src
            ):
                offenders.append(f"{path.name}: {src}")
    assert offenders == [], (
        "a quality floor is asserted against locked-test-window metrics:\n" + "\n".join(offenders)
    )


def test_both_controlled_arms_select_the_same_operating_point(prep, cfg):
    """The operating point is one of the things held fixed between the arms.

    If they selected independently and disagreed, the ablation would vary two
    things and the paired delta would stop being attributable. They share the
    selection code, the selection window and the snapshot indexes, so this
    should hold -- and it is asserted rather than assumed.
    """
    from pramaan_x.eval.oracle_target_retrieval import ABLATION

    strict = run_method(prep, cfg, STRICT, stages=("rerank",), write=False)
    ablation = run_method(prep, cfg, ABLATION, stages=("rerank",), write=False, reference=strict)
    assert (
        strict.payload["extra"]["operating_point"] == ablation.payload["extra"]["operating_point"]
    )
    assert (
        strict.payload["extra"]["selection"]["fingerprint"]
        == ablation.payload["extra"]["selection"]["fingerprint"]
    )
