"""Executable invariants for the evaluation firewall.

These are not assertions that the code ran. They are assertions about the
*scientific* validity of a run, and each one is written so that it fails on the
contaminated method and passes on the strict one. An invariant that both
methods satisfy is not testing anything.

Every function raises `InvariantViolation` with the offending records rather
than returning a boolean, because a leakage check whose result can be ignored
by a caller is decoration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from ..types import Document
from .availability import available_at, to_utc
from .oracle_target_retrieval import FitRecord, OracleTargetQuery, RunOutcome
from .protocol import TemporalProtocol


class InvariantViolation(AssertionError):
    """A run violated a stated property of the evaluation protocol."""


def assert_no_future_document_fitted(records: Sequence[FitRecord]) -> None:
    """Invariant 1: nothing fitted for origin O saw a document available at or
    after O.

    Checked against the recorded maximum availability timestamp of each fitted
    corpus, which is written at fit time by the index provider -- so this
    checks what was actually fitted, not what a filter was asked to do.
    """
    bad = []
    for r in records:
        if r.max_available_at is None:
            continue
        if datetime.fromisoformat(r.max_available_at) >= datetime.fromisoformat(r.origin):
            bad.append(r)
    if bad:
        head = "; ".join(
            f"origin {r.origin} fitted on {r.n_documents} docs up to {r.max_available_at}"
            for r in bad[:5]
        )
        raise InvariantViolation(
            f"{len(bad)} fitted corpora contain documents from at or after their "
            f"own forecast origin [{head}]"
        )


def assert_no_test_labels_in_training(
    train_queries: Sequence[OracleTargetQuery],
    test_queries: Sequence[OracleTargetQuery],
    protocol: TemporalProtocol,
    *,
    fitted_documents: Iterable[Document] = (),
) -> None:
    """Invariant 2: no test-window label, statistic or candidate outcome
    reached anything fitted.

    Three separate ways it could happen, all checked:
      * a training query whose event falls outside the training window;
      * a document marked relevant for a training query that was not available
        before the training window closed;
      * a training query id that also appears in the test set.
    """
    problems: list[str] = []
    for q in train_queries:
        if not protocol.contains("train", q.event_time):
            problems.append(f"train query {q.query_id} has event outside the train window")
        if not protocol.contains("train", q.origin):
            problems.append(f"train query {q.query_id} has origin outside the train window")

    train_ids = {q.query_id for q in train_queries}
    overlap = train_ids & {q.query_id for q in test_queries}
    if overlap:
        problems.append(
            f"{len(overlap)} query ids appear in both train and test: {sorted(overlap)[:3]}"
        )

    train_end = protocol.train_end
    by_id = {d.doc_id: d for d in fitted_documents}
    for q in train_queries:
        for doc_id in q.relevant:
            doc = by_id.get(doc_id)
            if doc is None:
                continue
            a = available_at(doc)
            if a is None or a >= train_end:
                problems.append(
                    f"train query {q.query_id} labels {doc_id}, available "
                    f"{a.isoformat() if a else 'never'}, at or after train_end"
                )
    if problems:
        raise InvariantViolation(
            f"{len(problems)} test-label leakage problems: " + "; ".join(problems[:5])
        )


def assert_lexicon_fitted_on_training_only(record, protocol: TemporalProtocol) -> None:
    """Invariant 2b: no test label reached *preprocessing*.

    The learned lexicon decides the text of every query in the benchmark,
    including the test queries. A document published after the label cutoff, or
    a label built from an event at or after the training window's end, would
    put information from beyond the training window into every query the
    retriever ever sees -- which no amount of careful indexing downstream can
    undo.
    """
    problems: list[str] = []
    if record.n_documents == 0:
        problems.append("the lexicon was fitted on no documents at all")
    cutoff = datetime.fromisoformat(record.label_cutoff)
    train_end = datetime.fromisoformat(record.train_end)
    if cutoff != protocol.label_cutoff:
        problems.append(
            f"lexicon label cutoff {record.label_cutoff} does not match the "
            f"protocol's {protocol.label_cutoff.isoformat()}"
        )
    if record.max_published_at is not None and (
        datetime.fromisoformat(record.max_published_at) >= cutoff
    ):
        problems.append(
            f"lexicon saw a document published {record.max_published_at}, "
            f"at or after the label cutoff {record.label_cutoff}"
        )
    if record.max_event_used is not None and (
        datetime.fromisoformat(record.max_event_used) >= train_end
    ):
        problems.append(
            f"a lexicon label used an event at {record.max_event_used}, "
            f"at or after train_end {record.train_end}"
        )
    if problems:
        raise InvariantViolation("; ".join(problems))


def assert_no_post_origin_results(outcome: RunOutcome) -> None:
    """Invariant 3: no document that postdates its query's origin was
    returned.

    This reads the run's own audit, which is computed from the documents that
    came back rather than from the filter that was supposed to exclude them.
    """
    if outcome.availability_violations:
        head = "; ".join(
            f"{v.doc_id} ({v.reason}) at origin {v.origin}"
            for v in outcome.availability_violations[:5]
        )
        raise InvariantViolation(
            f"{len(outcome.availability_violations)} returned documents violate the "
            f"availability rule [{head}]"
        )


def assert_future_append_invariance(
    build_and_rank: callable[[Sequence[Document]], dict[str, list[str]]],
    corpus: Sequence[Document],
    future_docs: Sequence[Document],
) -> dict[str, list[str]]:
    """Invariant 4: appending arbitrary future documents changes nothing.

    The decisive test. `build_and_rank` must build whatever it needs from the
    corpus it is handed and return ``{query_id: [ranked doc ids]}`` for a fixed
    set of queries at origins that precede every appended document. If any
    ranking moves, some statistic in the pipeline is a function of the future,
    and every number the pipeline produces is contaminated.

    Returns the baseline rankings so a caller can inspect them.
    """
    baseline = build_and_rank(list(corpus))
    perturbed = build_and_rank([*corpus, *future_docs])
    if set(baseline) != set(perturbed):
        raise InvariantViolation(
            "appending future documents changed the set of evaluated queries: "
            f"{sorted(set(baseline) ^ set(perturbed))[:5]}"
        )
    changed = [q for q in baseline if baseline[q] != perturbed[q]]
    if changed:
        q = changed[0]
        raise InvariantViolation(
            f"{len(changed)}/{len(baseline)} rankings changed when {len(future_docs)} "
            f"future documents were appended; first divergence on {q!r}: "
            f"{baseline[q][:5]} -> {perturbed[q][:5]}"
        )
    return baseline


def report_all(
    outcome: RunOutcome,
    protocol: TemporalProtocol,
    train_queries: Sequence[OracleTargetQuery],
    test_queries: Sequence[OracleTargetQuery],
    fitted_documents: Sequence[Document],
) -> dict[str, str]:
    """Same checks, reported rather than raised.

    The contaminated diagnostic is *expected* to fail these; recording how it
    fails is the point of running it, so the artefact carries the verdicts
    instead of the run dying before it can write one. The strict path calls
    `check_all`, which raises.
    """
    checks = (
        (
            "no_future_document_fitted",
            lambda: assert_no_future_document_fitted(outcome.fit_records),
        ),
        (
            "no_test_labels_in_training",
            lambda: assert_no_test_labels_in_training(
                train_queries, test_queries, protocol, fitted_documents=fitted_documents
            ),
        ),
        ("no_post_origin_results", lambda: assert_no_post_origin_results(outcome)),
    )
    out: dict[str, str] = {}
    for name, fn in checks:
        try:
            fn()
        except InvariantViolation as exc:
            out[name] = f"FAIL: {exc}"[:400]
        else:
            out[name] = "pass"
    return out


def check_all(
    outcome: RunOutcome,
    protocol: TemporalProtocol,
    train_queries: Sequence[OracleTargetQuery],
    test_queries: Sequence[OracleTargetQuery],
    fitted_documents: Sequence[Document],
) -> dict[str, str]:
    """Run every invariant that a completed run can answer on its own.

    Returns a name -> "pass" map. Raises on the first violation: a run whose
    firewall is broken has no results worth summarising.
    """
    assert_no_future_document_fitted(outcome.fit_records)
    assert_no_test_labels_in_training(
        train_queries, test_queries, protocol, fitted_documents=fitted_documents
    )
    assert_no_post_origin_results(outcome)
    return {
        "no_future_document_fitted": "pass",
        "no_test_labels_in_training": "pass",
        "no_post_origin_results": "pass",
    }


def synthesise_future_documents(
    corpus: Sequence[Document], n: int, *, after: datetime, seed: int = 0
) -> list[Document]:
    """Loud, obviously-post-origin documents for the invariance test.

    They are deliberately *maximally* attractive to the retriever: they copy
    the vocabulary of real documents in the corpus, so a pipeline whose
    statistics depend on the future will move visibly rather than subtly.
    """
    import random

    rng = random.Random(seed)
    after = to_utc(after)
    pool = list(corpus)
    out: list[Document] = []
    for i in range(n):
        src = pool[rng.randrange(len(pool))] if pool else None
        text = (
            src.full_text if src else "flood protest clash outage breach"
        ) + " confirmed today after the event was reported everywhere"
        stamp = after.replace(microsecond=0)
        out.append(
            Document(
                doc_id=f"future-{i:05d}",
                source_id="future_wire",
                title="post origin report",
                text=text,
                published_at=stamp,
                retrieved_at=stamp,
                meta={"source_family": "future", "synth_target": "none|none"},
            )
        )
    return out
