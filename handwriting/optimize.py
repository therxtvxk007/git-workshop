"""Stroke ordering.

Written in reading order, the pen spends much of its time in the air — every
dot on an 'i' is a round trip.  Reordering strokes cuts plot time substantially
and, more importantly, reduces the number of pen lifts, which is where cheap
servo pen-lifters make their mess.
"""

from __future__ import annotations

import math
from typing import Sequence

from .geometry import Stroke, travel_distance


def order_strokes(
    strokes: Sequence[Stroke],
    start: tuple[float, float] = (0.0, 0.0),
    allow_reverse: bool = True,
) -> list[Stroke]:
    """Greedy nearest-neighbour ordering of pen-down strokes.

    ``allow_reverse`` lets a stroke be drawn backwards when that end is
    nearer.  For a pen that is fine; it only matters for media where stroke
    direction is visible.
    """
    remaining = [list(s) for s in strokes if len(s) >= 2]
    ordered: list[Stroke] = []
    pen = start

    while remaining:
        best_i = 0
        best_d = math.inf
        best_rev = False
        for i, s in enumerate(remaining):
            d_head = math.dist(pen, s[0])
            if d_head < best_d:
                best_i, best_d, best_rev = i, d_head, False
            if allow_reverse:
                d_tail = math.dist(pen, s[-1])
                if d_tail < best_d:
                    best_i, best_d, best_rev = i, d_tail, True
        chosen = remaining.pop(best_i)
        if best_rev:
            chosen.reverse()
        ordered.append(chosen)
        pen = chosen[-1]

    return ordered


def optimize(
    strokes: Sequence[Stroke],
    start: tuple[float, float] = (0.0, 0.0),
    allow_reverse: bool = True,
) -> tuple[list[Stroke], float, float]:
    """Return ``(ordered, travel_before, travel_after)`` in millimetres.

    Reading order is already close to optimal for a single line of text, and
    a greedy tour that commits to a bad first hop can beat it going the wrong
    way.  So the original order is kept whenever greedy fails to improve on
    it: optimising must never make the plot slower.
    """
    kept = [list(s) for s in strokes if len(s) >= 2]
    before = travel_distance(kept)
    ordered = order_strokes(kept, start, allow_reverse)
    after = travel_distance(ordered)
    if after >= before:
        return kept, before, before
    return ordered, before, after
