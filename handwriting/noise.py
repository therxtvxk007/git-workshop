"""Deterministic noise.

Handwriting is irregular but not *random*: a hand drifts smoothly off the
baseline, it does not jump.  So variation here comes from smooth 1-D value
noise rather than independent per-point draws.

Everything is seeded and pure, so the same text plus the same seed always
produces the same page — which is what makes a preview trustworthy.
"""

from __future__ import annotations

import math

_MASK = 0xFFFFFFFF


def _hash01(seed: int, i: int) -> float:
    """Hash two ints to a float in ``[0, 1)``."""
    h = (seed * 0x9E3779B1 ^ (i & _MASK) * 0x85EBCA77) & _MASK
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & _MASK
    h ^= h >> 12
    h = (h * 0x297A2D39) & _MASK
    h ^= h >> 15
    return h / 4294967296.0


def rand(seed: int, *keys: int) -> float:
    """A stable pseudo-random float in ``[0, 1)`` for a tuple of int keys."""
    h = seed
    for k in keys:
        h = int(_hash01(h, k) * _MASK)
    return _hash01(h, 0x5BF03635)


def centered(seed: int, *keys: int) -> float:
    """Stable pseudo-random float in ``[-1, 1)``."""
    return rand(seed, *keys) * 2.0 - 1.0


def value_noise(seed: int, x: float) -> float:
    """Smooth 1-D noise in ``[-1, 1]``, one unit per lattice cell.

    Cosine interpolation between hashed lattice points: cheap, continuous,
    and good enough to read as an unsteady hand.
    """
    i = math.floor(x)
    t = x - i
    a = _hash01(seed, i)
    b = _hash01(seed, i + 1)
    # cosine ease makes the first derivative continuous at lattice points
    w = (1.0 - math.cos(t * math.pi)) * 0.5
    return (a + (b - a) * w) * 2.0 - 1.0


def fbm(seed: int, x: float, octaves: int = 2) -> float:
    """Fractal sum of :func:`value_noise`, normalised to roughly ``[-1, 1]``."""
    total = 0.0
    amplitude = 1.0
    norm = 0.0
    freq = 1.0
    for o in range(max(1, octaves)):
        total += value_noise(seed + o * 7919, x * freq) * amplitude
        norm += amplitude
        amplitude *= 0.5
        freq *= 2.0
    return total / norm
