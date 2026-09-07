"""Named random streams, derived from identity rather than from order.

A seed is not reproducibility. The plan is specific about why (S36.3): a run
that seeds one global generator and then draws from it in whatever order the
tasks happen to finish is reproducible only for that ordering. Add a district,
reorder two folds, parallelise a loop, and every downstream draw shifts.

So streams are addressed, not counted. ``streams.stream("predict", origin,
model)`` gives the same generator whatever else the run does, because the
spawn key comes from a hash of those words. Adding an eleventh model does not
renumber the other ten.

The bit generator is pinned. NumPy may change its default; a run replayed next
year must not quietly draw from a different algorithm.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Bumped only when the derivation below changes. Recorded in every ledger row,
#: because a changed derivation makes old draws unreproducible and that has to
#: be visible rather than inferred from a diff.
DERIVATION_SCHEME = "sha256-spawnkey-v1"

#: Pinned. ``np.random.default_rng`` is documented as free to change.
BIT_GENERATOR = "PCG64"

_SPAWN_WORDS = 4
_WORD_BITS = 32


def _spawn_key(parts: tuple[str, ...]) -> tuple[int, ...]:
    """A stable spawn key for a named stream.

    ``SeedSequence`` mixes the spawn key into the root entropy, so two names
    that differ anywhere give independent streams, and the same name always
    gives the same one. The digest is split into four 32-bit words because
    that is the width ``SeedSequence`` consumes without truncation.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return tuple(
        int.from_bytes(digest[index * 4 : index * 4 + 4], "big") for index in range(_SPAWN_WORDS)
    )


@dataclass(frozen=True)
class RandomStreams:
    """Every generator a run uses, addressed by name.

    Use one stream per purpose -- model fit, measurement uncertainty, predictive
    draws, audit sampling, bootstrap, stress tests -- so that changing the
    bootstrap replicate count does not move the predictive draws.
    """

    root_seed: int
    scheme: str = DERIVATION_SCHEME

    def __post_init__(self) -> None:
        if self.root_seed < 0:
            raise ValueError(f"root_seed must be non-negative, got {self.root_seed}")

    def seed_sequence(self, *parts: Any) -> np.random.SeedSequence:
        names = tuple(str(part) for part in parts)
        if not names:
            raise ValueError("a stream must be named; an anonymous stream is not reproducible")
        return np.random.SeedSequence(entropy=self.root_seed, spawn_key=_spawn_key(names))

    def stream(self, *parts: Any) -> np.random.Generator:
        """The generator for one named purpose."""
        return np.random.Generator(np.random.PCG64(self.seed_sequence(*parts)))

    def backend_seed(self, *parts: Any, bits: int = 32) -> int:
        """A derived integer seed for a backend with its own RNG.

        JAX keys, LightGBM and CatBoost do not share NumPy's stream. They get a
        seed derived here and recorded, rather than an assumption that seeding
        NumPy seeded them too.
        """
        return int(self.seed_sequence(*parts).generate_state(1, dtype=np.uint32)[0]) % (2**bits)

    def describe(self) -> dict[str, Any]:
        """What the ledger records so a replay can rebuild these streams."""
        return {
            "root_seed": self.root_seed,
            "scheme": self.scheme,
            "bit_generator": BIT_GENERATOR,
            "spawn_words": _SPAWN_WORDS,
            "word_bits": _WORD_BITS,
        }
