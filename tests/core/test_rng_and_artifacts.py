"""Reproducibility identity: named streams and dependency-aware artifact keys."""

from __future__ import annotations

import pytest

from pramaanx.core.artifacts import ArtifactKeyInputs, ArtifactRef, LineageIndex
from pramaanx.core.rng import BIT_GENERATOR, RandomStreams


def _draws(streams: RandomStreams, *name: str) -> list[int]:
    return streams.stream(*name).integers(0, 1_000_000, 8).tolist()


def test_a_named_stream_is_the_same_stream_every_time() -> None:
    streams = RandomStreams(root_seed=11)
    assert _draws(streams, "predict", "2026-01-01") == _draws(streams, "predict", "2026-01-01")


def test_different_names_give_independent_streams() -> None:
    streams = RandomStreams(root_seed=11)
    assert _draws(streams, "predict", "hist12") != _draws(streams, "predict", "zero")
    assert _draws(streams, "predict", "hist12") != _draws(streams, "bootstrap", "hist12")


def test_adding_a_task_does_not_renumber_existing_streams() -> None:
    """The reason streams are addressed rather than counted (S36.3).

    A counter-based scheme would shift every later stream when a model is
    inserted. Here the eleventh model cannot disturb the other ten, because
    nothing about their names changed.
    """
    streams = RandomStreams(root_seed=11)
    before = {name: _draws(streams, "fit", name) for name in ("zero", "climatology", "hist12")}
    _draws(streams, "fit", "empirical_bayes")
    after = {name: _draws(streams, "fit", name) for name in ("zero", "climatology", "hist12")}
    assert before == after


def test_a_different_root_seed_changes_every_stream() -> None:
    assert _draws(RandomStreams(root_seed=1), "fit", "x") != _draws(
        RandomStreams(root_seed=2), "fit", "x"
    )


def test_an_anonymous_stream_is_refused() -> None:
    with pytest.raises(ValueError, match="must be named"):
        RandomStreams(root_seed=1).stream()


def test_backend_seeds_are_derived_and_recorded() -> None:
    """A backend with its own RNG gets a derived seed, not an assumption."""
    streams = RandomStreams(root_seed=5)
    assert streams.backend_seed("fit", "lightgbm") == streams.backend_seed("fit", "lightgbm")
    assert streams.backend_seed("fit", "lightgbm") != streams.backend_seed("fit", "catboost")
    assert streams.describe()["bit_generator"] == BIT_GENERATOR


# -- artifact keys ---------------------------------------------------------
def _inputs(**overrides: object) -> ArtifactKeyInputs:
    base: dict[str, object] = {
        "stage": "features.history",
        "stage_version": 1,
        "code_hash": "sha256:code",
        "config": {"windows": [7, 30]},
        "inputs": ("sha256:panel",),
        "policy_hash": "sha256:policy",
    }
    base.update(overrides)
    return ArtifactKeyInputs.model_validate(base)


def test_the_same_inputs_give_the_same_key() -> None:
    assert _inputs().key() == _inputs().key()


@pytest.mark.parametrize(
    "field, value",
    [
        ("stage_version", 2),
        ("code_hash", "sha256:other"),
        ("config", {"windows": [7, 30, 90]}),
        ("inputs", ("sha256:panel-v2",)),
        ("policy_hash", "sha256:policy-with-shadow"),
        ("fitted", ("sha256:translator-v3",)),
        ("numeric_environment", {"threads": 4}),
        ("rng", {"root_seed": 1}),
    ],
)
def test_one_changed_semantic_dependency_changes_the_key(field: str, value: object) -> None:
    """Each of these is a dependency the plan names explicitly (S36.2).

    A boundary update, a corrected linkage or a shadow-source reassignment
    reaches the key through ``inputs`` or ``policy_hash``; if any of them did
    not, a stale artifact would keep being served as current.
    """
    assert _inputs(**{field: value}).key() != _inputs().key()


def test_input_order_is_part_of_the_key() -> None:
    ordered = _inputs(inputs=("a", "b"))
    swapped = _inputs(inputs=("b", "a"))
    assert ordered.key() != swapped.key()


def test_an_artifact_ref_keeps_key_and_content_apart() -> None:
    """Two runs of a non-deterministic stage share a key and differ in content."""
    first = ArtifactRef(kind="forecast", artifact_key="sha256:k", content_digest="sha256:a")
    second = ArtifactRef(kind="forecast", artifact_key="sha256:k", content_digest="sha256:b")
    assert first.artifact_key == second.artifact_key
    assert first.content_digest != second.content_digest


# -- lineage ---------------------------------------------------------------
def test_lineage_finds_the_descendants_a_withdrawn_source_invalidates() -> None:
    """Withholding by source id misses the translation and the cache.

    ``raw`` feeds a translation, which feeds an extraction, which feeds a
    feature table and then a forecast. Removing ``raw`` invalidates all four,
    and none of them carries the source id in its own name.
    """
    index = (
        LineageIndex()
        .record("translation", ["raw"])
        .record("extraction", ["translation"])
        .record("features", ["extraction", "panel"])
        .record("forecast", ["features"])
    )
    assert index.descendants("raw") == ("extraction", "features", "forecast", "translation")
    assert index.descendants("forecast") == ()
    assert index.ancestors("forecast") == (
        "extraction",
        "features",
        "panel",
        "raw",
        "translation",
    )


def test_lineage_survives_a_cycle_without_hanging() -> None:
    """Defensive: a mis-recorded cycle must not spin forever."""
    index = LineageIndex().record("a", ["b"]).record("b", ["a"])
    assert set(index.descendants("a")) == {"a", "b"}
