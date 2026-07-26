"""Stroke geometry.

A *point* is an ``(x, y)`` tuple in millimetres.  A *stroke* is a list of
points the pen draws without lifting.  Glyph space is y-up with the baseline
at ``y = 0``; page space is y-down with the origin at the top-left corner of
the paper.  :class:`Affine` is what moves between them.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]
Stroke = list[Point]


# --------------------------------------------------------------------------
# basic measurements
# --------------------------------------------------------------------------

def dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def stroke_length(stroke: Sequence[Point]) -> float:
    return sum(dist(stroke[i], stroke[i + 1]) for i in range(len(stroke) - 1))


def bbox(strokes: Iterable[Sequence[Point]]) -> tuple[float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y)`` over every point.

    Raises ``ValueError`` if there are no points at all, since an empty box
    has no meaningful position and silently returning zeros hides bugs.
    """
    xs: list[float] = []
    ys: list[float] = []
    for stroke in strokes:
        for x, y in stroke:
            xs.append(x)
            ys.append(y)
    if not xs:
        raise ValueError("bbox of an empty stroke set")
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------
# affine transforms (SVG matrix convention)
# --------------------------------------------------------------------------

class Affine:
    """2x3 affine transform: ``x' = a*x + c*y + e``, ``y' = b*x + d*y + f``."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    # -- constructors ------------------------------------------------------
    @staticmethod
    def translate(tx: float, ty: float) -> "Affine":
        return Affine(1, 0, 0, 1, tx, ty)

    @staticmethod
    def scale(sx: float, sy: float | None = None) -> "Affine":
        return Affine(sx, 0, 0, sx if sy is None else sy, 0, 0)

    @staticmethod
    def rotate(degrees: float) -> "Affine":
        r = math.radians(degrees)
        cos, sin = math.cos(r), math.sin(r)
        return Affine(cos, sin, -sin, cos, 0, 0)

    @staticmethod
    def skew_x(degrees: float) -> "Affine":
        return Affine(1, 0, math.tan(math.radians(degrees)), 1, 0, 0)

    # -- algebra -----------------------------------------------------------
    def then(self, other: "Affine") -> "Affine":
        """Return the transform that applies ``self`` first, then ``other``."""
        return Affine(
            other.a * self.a + other.c * self.b,
            other.b * self.a + other.d * self.b,
            other.a * self.c + other.c * self.d,
            other.b * self.c + other.d * self.d,
            other.a * self.e + other.c * self.f + other.e,
            other.b * self.e + other.d * self.f + other.f,
        )

    def apply(self, p: Point) -> Point:
        x, y = p
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def apply_stroke(self, stroke: Sequence[Point]) -> Stroke:
        return [self.apply(p) for p in stroke]


# --------------------------------------------------------------------------
# resampling and simplification
# --------------------------------------------------------------------------

def resample(stroke: Sequence[Point], spacing: float) -> Stroke:
    """Re-space a stroke's points evenly, ``spacing`` mm apart.

    Digitiser samples bunch up wherever the pen slowed down; even spacing
    makes downstream noise and smoothing behave predictably.
    """
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    if len(stroke) < 2:
        return list(stroke)

    out: Stroke = [tuple(stroke[0])]  # type: ignore[list-item]
    carry = 0.0
    for i in range(len(stroke) - 1):
        p, q = stroke[i], stroke[i + 1]
        seg = dist(p, q)
        if seg == 0:
            continue
        travelled = carry
        while travelled + spacing <= seg:
            travelled += spacing
            t = travelled / seg
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        carry = travelled - seg
    last = tuple(stroke[-1])
    if dist(out[-1], last) > spacing * 0.25:  # type: ignore[arg-type]
        out.append(last)  # type: ignore[arg-type]
    return out


def _perp_distance(p: Point, a: Point, b: Point) -> float:
    if a == b:
        return dist(p, a)
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = math.hypot(dx, dy)
    return abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / denom


def simplify(stroke: Sequence[Point], tolerance: float) -> Stroke:
    """Ramer-Douglas-Peucker. Drops points that sit within ``tolerance`` mm
    of the line they'd be interpolated onto anyway."""
    if tolerance <= 0 or len(stroke) < 3:
        return list(stroke)

    keep = [False] * len(stroke)
    keep[0] = keep[-1] = True
    stack = [(0, len(stroke) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        worst, worst_i = 0.0, lo
        for i in range(lo + 1, hi):
            d = _perp_distance(stroke[i], stroke[lo], stroke[hi])
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.append((lo, worst_i))
            stack.append((worst_i, hi))
    return [p for p, k in zip(stroke, keep) if k]


def smooth(stroke: Sequence[Point], iterations: int = 1) -> Stroke:
    """Chaikin corner cutting. Rounds off the polygonal look of raw samples
    while keeping the endpoints pinned."""
    pts = list(stroke)
    for _ in range(max(0, iterations)):
        if len(pts) < 3:
            break
        out: Stroke = [pts[0]]
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            out.append((p[0] * 0.75 + q[0] * 0.25, p[1] * 0.75 + q[1] * 0.25))
            out.append((p[0] * 0.25 + q[0] * 0.75, p[1] * 0.25 + q[1] * 0.75))
        out.append(pts[-1])
        pts = out
    return pts


def travel_distance(strokes: Sequence[Sequence[Point]]) -> float:
    """Total pen-up movement: the air miles between one stroke's end and the
    next stroke's start."""
    total = 0.0
    for i in range(len(strokes) - 1):
        if strokes[i] and strokes[i + 1]:
            total += dist(strokes[i][-1], strokes[i + 1][0])
    return total
