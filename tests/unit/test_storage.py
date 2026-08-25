"""Content-addressed payloads and deterministic Parquet tables."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pramaanx.hashing import hash_bytes
from pramaanx.ingest.ledger import OBSERVATION_SPEC
from pramaanx.schemas.observation import Modality, Observation
from pramaanx.storage import PayloadStore, RecordTable

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def observation(index: int, source: str = "synthetic") -> Observation:
    payload = f"document-{index}".encode()
    return Observation(
        observation_id=f"obs_{index:03d}",
        source_id=source,
        source_type="synthetic",
        modality=Modality.TEXT,
        retrieved_at=NOW,
        first_observed_at=NOW,
        raw_content_hash=hash_bytes(payload),
        payload_ref=f"ab/cd/{index}.bin",
    )


class TestPayloadStore:
    def test_same_bytes_store_once(self, tmp_path: Path) -> None:
        store = PayloadStore(tmp_path)
        first_hash, first_ref = store.put(b"evidence")
        second_hash, second_ref = store.put(b"evidence")
        assert (first_hash, first_ref) == (second_hash, second_ref)
        assert len(list(tmp_path.rglob("*.bin"))) == 1

    def test_round_trip(self, tmp_path: Path) -> None:
        store = PayloadStore(tmp_path)
        content_hash, ref = store.put(b"evidence")
        assert store.get(ref) == b"evidence"
        assert store.verify(ref, content_hash)

    def test_verify_detects_mutation(self, tmp_path: Path) -> None:
        store = PayloadStore(tmp_path)
        content_hash, ref = store.put(b"evidence")
        (tmp_path / ref).write_bytes(b"tampered")
        assert not store.verify(ref, content_hash)

    def test_missing_payload_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PayloadStore(tmp_path).get("no/such/ref.bin")


class TestRecordTable:
    def test_append_and_read_round_trip(self, tmp_path: Path) -> None:
        table = RecordTable(tmp_path, OBSERVATION_SPEC)
        records = [observation(index) for index in range(5)]
        result = table.append(records)
        assert result.written == 5
        restored = table.read_models(Observation)
        assert [item.observation_id for item in restored] == [
            item.observation_id for item in records
        ]

    def test_appending_the_same_records_twice_is_a_no_op(self, tmp_path: Path) -> None:
        table = RecordTable(tmp_path, OBSERVATION_SPEC)
        records = [observation(index) for index in range(3)]
        table.append(records)
        second = table.append(records)
        assert second.written == 0
        assert second.skipped == 3
        assert table.count() == 3

    def test_identical_batches_produce_identical_file_names(self, tmp_path: Path) -> None:
        # Determinism of layout is what allows byte-level comparison of runs.
        records = [observation(index) for index in range(4)]
        first = RecordTable(tmp_path / "a", OBSERVATION_SPEC).append(records)
        second = RecordTable(tmp_path / "b", OBSERVATION_SPEC).append(records)
        assert first.files == second.files

    def test_partitioning_splits_by_source_and_date(self, tmp_path: Path) -> None:
        table = RecordTable(tmp_path, OBSERVATION_SPEC)
        table.append([observation(1, "synthetic"), observation(2, "gdelt")])
        partitions = {path.parent.parent.name for path in table.files}
        assert partitions == {"source_id=synthetic", "source_id=gdelt"}

    def test_reads_are_sorted_by_key(self, tmp_path: Path) -> None:
        table = RecordTable(tmp_path, OBSERVATION_SPEC)
        table.append([observation(3), observation(1), observation(2)])
        ids = [item.observation_id for item in table.read_models(Observation)]
        assert ids == sorted(ids)

    def test_empty_table_reads_cleanly(self, tmp_path: Path) -> None:
        table = RecordTable(tmp_path, OBSERVATION_SPEC)
        assert table.is_empty()
        assert table.count() == 0
        assert table.read_models(Observation) == []
