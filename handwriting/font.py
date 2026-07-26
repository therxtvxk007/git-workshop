"""The handwriting font: your letters, as strokes.

A font is a JSON file holding, for each character, one or more *variants* —
separate times you wrote that letter.  Multiple variants are what stop the
output looking like a typeface: the layout engine picks a different one each
time the letter appears.

Glyph coordinates are millimetres in glyph space: baseline at ``y = 0``,
y-up, pen starting near ``x = 0``.  All sizes scale from ``metrics.em``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from .geometry import Point, Stroke, bbox, simplify, smooth

FORMAT = "handwriting-machine/font"
VERSION = 1


@dataclass
class Metrics:
    """Vertical proportions, in the same millimetre units as the glyphs."""

    em: float = 10.0          # ascender-to-descender, the size everything scales from
    x_height: float = 5.0
    cap_height: float = 7.0
    ascender: float = 7.5
    descender: float = -2.5
    space_advance: float = 2.6

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Metrics":
        known = {f: d[f] for f in Metrics.__dataclass_fields__ if f in d}
        return Metrics(**known)


@dataclass
class Variant:
    """One recorded instance of a character."""

    strokes: list[Stroke]
    advance: float
    entry: Point | None = None   # where a joining stroke should arrive
    exit: Point | None = None    # where a joining stroke should leave

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "strokes": [[[round(x, 4), round(y, 4)] for x, y in s] for s in self.strokes],
            "advance": round(self.advance, 4),
        }
        if self.entry is not None:
            d["entry"] = [round(self.entry[0], 4), round(self.entry[1], 4)]
        if self.exit is not None:
            d["exit"] = [round(self.exit[0], 4), round(self.exit[1], 4)]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Variant":
        strokes = [[(float(p[0]), float(p[1])) for p in s] for s in d.get("strokes", [])]
        entry = tuple(d["entry"]) if d.get("entry") else None
        exit_ = tuple(d["exit"]) if d.get("exit") else None
        advance = d.get("advance")
        if advance is None:
            advance = (bbox(strokes)[2] + 0.5) if any(strokes) else 0.0
        return Variant(strokes, float(advance), entry, exit_)  # type: ignore[arg-type]


def _as_stroke_list(item: list[Any]) -> list[Any]:
    """Accept either one stroke or a list of strokes.

    Hand-written font files nest lists three or four deep depending on
    whether the author wrote a single stroke or several, and guessing wrong
    silently produces garbage glyphs.  Depth is checked instead: a stroke's
    first element is a point, whose first element is a number.
    """
    if not item:
        return []
    first = item[0]
    if isinstance(first, (int, float)):
        raise ValueError("expected a stroke (list of points), got a bare point")
    if first and isinstance(first[0], (int, float)):
        return [item]           # a single stroke
    return item                 # already a list of strokes


class Font:
    """A character-to-variants mapping plus metrics."""

    def __init__(
        self,
        name: str = "untitled",
        metrics: Metrics | None = None,
        glyphs: dict[str, list[Variant]] | None = None,
        kerning: dict[str, float] | None = None,
        joins: bool = False,
    ):
        self.name = name
        self.metrics = metrics or Metrics()
        self.glyphs: dict[str, list[Variant]] = glyphs or {}
        self.kerning: dict[str, float] = kerning or {}
        self.joins = joins

    # -- lookup ------------------------------------------------------------
    def has(self, char: str) -> bool:
        return bool(self.glyphs.get(char))

    def variants(self, char: str) -> list[Variant]:
        return self.glyphs.get(char, [])

    def variant(self, char: str, index: int) -> Variant | None:
        vs = self.glyphs.get(char)
        if not vs:
            return None
        return vs[index % len(vs)]

    def kern(self, left: str, right: str) -> float:
        return self.kerning.get(left + right, 0.0)

    def add(self, char: str, variant: Variant) -> None:
        self.glyphs.setdefault(char, []).append(variant)

    def missing(self, text: str) -> list[str]:
        """Characters in ``text`` this font cannot draw (whitespace excluded)."""
        seen: list[str] = []
        for ch in text:
            if ch.isspace() or self.has(ch) or ch in seen:
                continue
            seen.append(ch)
        return seen

    # -- bulk edits --------------------------------------------------------
    def clean(self, tolerance: float = 0.05, smooth_passes: int = 1) -> "Font":
        """Simplify and smooth every stroke; drop degenerate ones.

        Raw captures carry far more points than a plotter needs, and the
        tablet jitter in them shows up as visible fuzz on paper.
        """
        for variants in self.glyphs.values():
            for v in variants:
                cleaned: list[Stroke] = []
                for stroke in v.strokes:
                    s = simplify(stroke, tolerance)
                    if smooth_passes:
                        s = smooth(s, smooth_passes)
                    if len(s) >= 2 or (len(s) == 1 and len(stroke) == 1):
                        cleaned.append(s)
                v.strokes = cleaned
        return self

    def merge(self, other: "Font") -> "Font":
        """Fold another font's variants into this one.

        Lets you capture in several sittings and combine the sessions — more
        variants per letter is strictly better for realism.
        """
        for char, variants in other.glyphs.items():
            self.glyphs.setdefault(char, []).extend(variants)
        self.kerning.update(other.kerning)
        return self

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": VERSION,
            "name": self.name,
            "units": "mm",
            "joins": self.joins,
            "metrics": asdict(self.metrics),
            "kerning": self.kerning,
            "glyphs": {
                ch: [v.to_dict() for v in vs]
                for ch, vs in sorted(self.glyphs.items())
            },
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Font":
        fmt = d.get("format")
        if fmt is not None and fmt != FORMAT:
            raise ValueError(f"not a handwriting font file (format={fmt!r})")
        glyphs: dict[str, list[Variant]] = {}
        for ch, raw in d.get("glyphs", {}).items():
            # A bare list of strokes is accepted as a single variant, so
            # hand-written font files stay easy to author.
            if isinstance(raw, dict):
                raw = raw.get("variants", [])
            entries = raw if isinstance(raw, list) else []
            variants = []
            for item in entries:
                if isinstance(item, list):
                    item = {"strokes": _as_stroke_list(item)}
                variants.append(Variant.from_dict(item))
            if variants:
                glyphs[ch] = variants
        return Font(
            name=d.get("name", "untitled"),
            metrics=Metrics.from_dict(d.get("metrics", {})),
            glyphs=glyphs,
            kerning={k: float(v) for k, v in d.get("kerning", {}).items()},
            joins=bool(d.get("joins", False)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "Font":
        return Font.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        chars = sorted(self.glyphs)
        total_variants = sum(len(v) for v in self.glyphs.values())
        total_strokes = sum(len(v.strokes) for vs in self.glyphs.values() for v in vs)
        thin = [c for c, vs in self.glyphs.items() if len(vs) < 2]
        lines = [
            f"font        {self.name}",
            f"characters  {len(chars)}",
            f"variants    {total_variants} ({total_variants / max(1, len(chars)):.1f} per character)",
            f"strokes     {total_strokes}",
            f"em / x-hgt  {self.metrics.em:g} / {self.metrics.x_height:g} mm",
            f"joins       {'yes' if self.joins else 'no'}",
            f"covered     {''.join(chars)}",
        ]
        if thin:
            lines.append(
                f"note        {len(thin)} character(s) have only one variant, so they "
                f"will repeat identically: {''.join(sorted(thin))}"
            )
        return "\n".join(lines)


def normalise_variant(
    strokes: Iterable[Stroke],
    baseline_y: float,
    unit_scale: float,
    side_bearing: float = 0.35,
) -> Variant:
    """Convert captured strokes into glyph space.

    ``baseline_y`` is the baseline in the capture's own coordinates and
    ``unit_scale`` converts those coordinates to millimetres.  Capture
    surfaces are y-down, so the y axis is flipped here.  The glyph is shifted
    so its leftmost ink sits at ``side_bearing``.
    """
    strokes = [list(s) for s in strokes if len(s) >= 1]
    if not strokes:
        return Variant([], 0.0)

    flipped = [[(x * unit_scale, (baseline_y - y) * unit_scale) for x, y in s] for s in strokes]
    min_x, _, max_x, _ = bbox(flipped)
    shift = side_bearing - min_x
    moved = [[(x + shift, y) for x, y in s] for s in flipped]

    advance = (max_x + shift) + side_bearing
    entry = moved[0][0]
    exit_ = moved[-1][-1]
    return Variant(moved, advance, entry, exit_)
