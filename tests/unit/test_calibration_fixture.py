"""Unit tests for the calibration fixture contract.

These build samples by hand. The question here is whether the container
enforces its own invariants and whether drift is detected -- not whether the
synthetic world reproduces, which is the integration test's job.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pramaanx.fixtures import (
    CalibrationSample,
    FixtureDriftError,
    FixtureManifest,
    build_manifest,
    verify_manifest,
)
from pramaanx.fixtures.calibration import MANIFEST_VERSION, SYNTHETIC_CAVEAT, FoldSlice

CUTOFF = datetime(2026, 1, 7, tzinfo=UTC)


def _fold(index: int, start: int, stop: int) -> FoldSlice:
    return FoldSlice(cutoff_at=datetime(2026, 1, 7 + index, tzinfo=UTC), start=start, stop=stop)


def _sample(
    probabilities: tuple[float, ...] = (0.1, 0.9, 0.4, 0.6),
    labels: tuple[int, ...] = (0, 1, 0, 1),
    folds: tuple[FoldSlice, ...] | None = None,
) -> CalibrationSample:
    return CalibrationSample(
        probabilities=probabilities,
        labels=labels,
        folds=folds if folds is not None else (_fold(0, 0, 2), _fold(1, 2, 4)),
        experiment="unit",
        code_hash="sha256:code",
    )


class TestInvariants:
    def test_misaligned_arrays_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="misaligned"):
            _sample(probabilities=(0.1, 0.2, 0.3), labels=(0, 1))

    def test_non_binary_labels_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="labels must be 0 or 1"):
            _sample(probabilities=(0.1, 0.2), labels=(0, 2), folds=(_fold(0, 0, 2),))

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_out_of_range_probabilities_are_rejected(self, bad: float) -> None:
        with pytest.raises(ValueError, match=r"probabilities must lie"):
            _sample(probabilities=(0.5, bad), labels=(0, 1), folds=(_fold(0, 0, 2),))

    def test_fold_slices_must_cover_every_row(self) -> None:
        # A fold set that covers three of four rows would silently drop the
        # fourth from any temporal split.
        with pytest.raises(ValueError, match="cover 3 rows but the sample holds 4"):
            _sample(folds=(_fold(0, 0, 2), _fold(1, 2, 3)))

    def test_base_rate_and_positives(self) -> None:
        sample = _sample()
        assert sample.positives == 2
        assert sample.base_rate == pytest.approx(0.5)
        assert len(sample) == 4

    def test_caveat_travels_with_the_sample(self) -> None:
        assert "not with reality" in _sample().caveat
        assert _sample().caveat == SYNTHETIC_CAVEAT


class TestTemporalSplit:
    def test_split_partitions_on_a_fold_boundary(self) -> None:
        earlier, later = _sample().split_at_fold(1)
        assert earlier.probabilities == (0.1, 0.9)
        assert later.probabilities == (0.4, 0.6)
        assert len(earlier) + len(later) == 4

    def test_split_rebases_fold_indices(self) -> None:
        _, later = _sample().split_at_fold(1)
        # The later half must index from zero, or slicing it again would read
        # past the end of its own arrays.
        assert later.folds[0].start == 0
        assert later.folds[0].stop == 2

    def test_split_preserves_fold_identity(self) -> None:
        _, later = _sample().split_at_fold(1)
        assert later.folds[0].cutoff_at == datetime(2026, 1, 8, tzinfo=UTC)

    @pytest.mark.parametrize("index", [0, 2, -1, 5])
    def test_split_refuses_an_empty_side(self, index: int) -> None:
        with pytest.raises(ValueError, match="strictly inside"):
            _sample().split_at_fold(index)

    def test_no_random_split_is_offered(self) -> None:
        # Conformal coverage assumes exchangeability; a random split would hide
        # the temporal violation rather than expose it.
        assert not [name for name in dir(_sample()) if "random" in name or "shuffle" in name]


class TestFingerprint:
    def test_identical_samples_agree(self) -> None:
        assert _sample().fingerprint() == _sample().fingerprint()

    def test_a_changed_label_changes_the_fingerprint(self) -> None:
        other = _sample(labels=(0, 1, 1, 1))
        assert other.fingerprint() != _sample().fingerprint()

    def test_provenance_is_not_part_of_the_fingerprint(self) -> None:
        # The fingerprint answers "is this the same sample", so it must not
        # move when only the surrounding metadata does.
        shifted = CalibrationSample(
            probabilities=_sample().probabilities,
            labels=_sample().labels,
            folds=_sample().folds,
            experiment="different",
            code_hash="sha256:other",
        )
        assert shifted.fingerprint() == _sample().fingerprint()


class TestManifest:
    def test_round_trips_through_a_file(self, tmp_path) -> None:
        manifest = build_manifest(_sample())
        path = tmp_path / "pinned.json"
        manifest.write(path)
        assert FixtureManifest.read(path) == manifest

    def test_records_the_shape_of_the_sample(self) -> None:
        manifest = build_manifest(_sample())
        assert manifest.rows == 4
        assert manifest.positives == 2
        assert manifest.folds == 2
        assert manifest.manifest_version == MANIFEST_VERSION
        assert manifest.cutoffs == (
            "2026-01-07T00:00:00.000000Z",
            "2026-01-08T00:00:00.000000Z",
        )

    def test_an_unchanged_sample_verifies(self) -> None:
        verify_manifest(_sample(), build_manifest(_sample()))

    def test_a_changed_sample_is_drift(self) -> None:
        pinned = build_manifest(_sample())
        with pytest.raises(FixtureDriftError, match="sample_fingerprint"):
            verify_manifest(_sample(labels=(1, 1, 1, 1)), pinned)

    def test_drift_without_a_code_change_names_non_determinism(self) -> None:
        pinned = build_manifest(_sample())
        with pytest.raises(FixtureDriftError, match="NOT deterministic"):
            verify_manifest(_sample(labels=(1, 1, 1, 1)), pinned)

    def test_drift_with_a_code_change_is_reported_as_possibly_intended(self) -> None:
        pinned = build_manifest(_sample())
        moved = CalibrationSample(
            probabilities=_sample().probabilities,
            labels=(1, 1, 1, 1),
            folds=_sample().folds,
            experiment="unit",
            code_hash="sha256:different",
        )
        with pytest.raises(FixtureDriftError, match="may be an intended update"):
            verify_manifest(moved, pinned)

    def test_a_code_only_move_is_not_drift(self) -> None:
        # The sample is identical and only the source tree moved. Failing here
        # would make every unrelated source edit demand a re-pin, and a fixture
        # re-pinned reflexively verifies nothing.
        pinned = build_manifest(_sample())
        moved = CalibrationSample(
            probabilities=_sample().probabilities,
            labels=_sample().labels,
            folds=_sample().folds,
            experiment="unit",
            code_hash="sha256:different",
        )
        verify_manifest(moved, pinned)

    def test_nothing_path_dependent_is_pinned(self) -> None:
        # config_hash embeds storage.data_root, so anything derived from it --
        # snapshot hashes, forecast identifiers -- differs between machines.
        # Pinning one would produce a fixture that reproduces on exactly one box.
        payload = build_manifest(_sample()).to_dict()
        assert "config_hash" not in payload
        assert "snapshot_hashes" not in payload
