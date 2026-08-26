"""Canonical serialisation and content hashing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pramaanx.hashing import (
    canonical_json,
    hash_bytes,
    hash_file,
    hash_object,
    merkle_root,
    stable_id,
    utc_isoformat,
)


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_normalises_equivalent_instants() -> None:
    utc = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    other = utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert canonical_json({"t": utc}) == canonical_json({"t": other})


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="naive datetime"):
        utc_isoformat(datetime(2026, 1, 15, 12, 0))  # noqa: DTZ001


def test_hash_object_is_stable_across_processes() -> None:
    # Guards against anything reaching for the salted built-in hash().
    payload = {"actor": "Farmers Union Federation", "region": "IN-DL"}
    assert hash_object(payload) == (
        "sha256:" + hash_bytes(canonical_json(payload).encode()).removeprefix("sha256:")
    )


def test_stable_id_depends_only_on_content() -> None:
    first = stable_id("obs", "gdelt", "abc", 1)
    second = stable_id("obs", "gdelt", "abc", 1)
    third = stable_id("obs", "gdelt", "abc", 2)
    assert first == second
    assert first != third
    assert first.startswith("obs_")


def test_merkle_root_ignores_order_but_not_membership() -> None:
    hashes = [hash_bytes(b"a"), hash_bytes(b"b"), hash_bytes(b"c")]
    assert merkle_root(hashes) == merkle_root(reversed(hashes))
    assert merkle_root(hashes) != merkle_root(hashes[:2])


def test_hash_file_matches_hash_bytes(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"evidence")
    assert hash_file(target) == hash_bytes(b"evidence")


def test_nan_is_not_serialisable() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        canonical_json({"probability": float("nan")})
