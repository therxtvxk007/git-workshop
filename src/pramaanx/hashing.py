"""Content hashing and canonical serialisation.

Every claim this project makes about accuracy depends on being able to say
*exactly* which bytes went in. That requires one canonical serialisation used
everywhere: sorted keys, no incidental whitespace, timezone-aware UTC timestamps
rendered identically on every machine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

HASH_ALGORITHM = "sha256"
HASH_PREFIX = f"{HASH_ALGORITHM}:"
_CHUNK = 1 << 20


def utc_isoformat(value: datetime) -> str:
    """Render a timezone-aware datetime as a canonical UTC ISO-8601 string.

    Naive datetimes are rejected rather than silently assumed to be UTC: a
    forecasting system that guesses timezones will eventually guess a leak.
    """
    if value.tzinfo is None:
        raise ValueError(f"naive datetime is not permitted: {value!r}")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return utc_isoformat(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(_default(item) if not isinstance(item, str) else item for item in obj)
    if isinstance(obj, Path):
        return obj.as_posix()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"object of type {type(obj).__name__} is not canonically serialisable")


def canonical_json(payload: Any) -> str:
    """Serialise ``payload`` deterministically."""
    return json.dumps(
        payload,
        default=_default,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8")


def hash_bytes(data: bytes) -> str:
    """Return a prefixed content hash, e.g. ``sha256:1a2b...``."""
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def hash_text(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))


def hash_object(payload: Any) -> str:
    """Hash any canonically serialisable object."""
    return hash_bytes(canonical_bytes(payload))


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()


def hash_hash_list(hashes: Iterable[str]) -> str:
    """Combine many content hashes into one order-independent digest.

    Sorting first means the digest describes the *set* of observations in a
    snapshot, not the order a connector happened to return them in.
    """
    return hash_object(sorted(hashes))


def hash_tree(root: Path, patterns: Iterable[str] = ("**/*.py",)) -> str:
    """Hash a source tree, so a run manifest can pin the code that produced it."""
    entries: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            entries[path.relative_to(root).as_posix()] = hash_file(path)
    return hash_object(entries)


def short_hash(value: str, length: int = 12) -> str:
    """Trim a prefixed hash for use inside identifiers."""
    return value.removeprefix(HASH_PREFIX)[:length]


def stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    """Build a deterministic identifier from its semantic content.

    Identifiers must never come from ``uuid4`` or a wall clock: two runs over the
    same evidence have to produce the same identifiers, or reproducibility tests
    cannot distinguish a real change from a fresh random draw.
    """
    digest = hash_object(list(parts))
    return f"{prefix}_{short_hash(digest, length)}"


def merkle_root(hashes: Iterable[str]) -> str:
    """Order-independent Merkle-style root over a set of content hashes."""
    layer = sorted(set(hashes))
    if not layer:
        return hash_object([])
    while len(layer) > 1:
        nxt: list[str] = []
        for index in range(0, len(layer), 2):
            pair = layer[index : index + 2]
            nxt.append(hash_text("".join(pair)) if len(pair) == 2 else pair[0])
        layer = sorted(nxt)
    return layer[0]


def hash_mapping_values(mapping: Mapping[str, Any]) -> dict[str, str]:
    return {key: hash_object(value) for key, value in sorted(mapping.items())}
