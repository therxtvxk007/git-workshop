"""Text -> positioned strokes on a page.

Output is in page space: millimetres, origin at the top-left of the paper,
y increasing downward.  That matches SVG directly; the G-code writer flips it
back to machine coordinates.

What makes the result look handwritten rather than typeset:

* a different recorded variant of a letter each time it appears;
* per-letter scale, rotation, vertical offset and advance wobble;
* per-word slant and size drift, because a hand doesn't reset between words;
* a baseline that wanders smoothly along each line (unruled paper effect);
* low-frequency tremor along each stroke, so no line is perfectly straight.

Every one of those is driven by seeded noise, so a given ``(text, seed)``
always lays out identically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import noise
from .font import Font, Variant
from .geometry import Affine, Point, Stroke, resample, stroke_length


@dataclass
class PageSetup:
    """Paper and margins, in millimetres."""

    width: float = 210.0        # A4 portrait
    height: float = 297.0
    margin_left: float = 20.0
    margin_right: float = 20.0
    margin_top: float = 20.0
    margin_bottom: float = 20.0

    @property
    def content_width(self) -> float:
        return self.width - self.margin_left - self.margin_right

    @property
    def content_height(self) -> float:
        return self.height - self.margin_top - self.margin_bottom

    def validate(self) -> None:
        if self.content_width <= 0 or self.content_height <= 0:
            raise ValueError("margins leave no room to write on the page")


@dataclass
class Style:
    """How the hand behaves.  Defaults are a relaxed, mostly-upright hand."""

    size: float = 6.0             # em height in mm; x-height ends up ~3mm
    line_spacing: float = 1.9     # multiples of em
    word_spacing: float = 1.0     # multiplier on the font's space advance
    letter_spacing: float = 0.0   # extra mm between letters
    slant: float = 0.0            # degrees; positive leans right
    align: str = "left"           # left | center | right

    # -- irregularity (0 disables each one individually) -------------------
    size_jitter: float = 0.04     # fraction, per letter
    rotation_jitter: float = 2.0  # degrees, per letter
    offset_jitter: float = 0.10   # fraction of em, vertical, per letter
    advance_jitter: float = 0.05  # fraction of advance
    slant_jitter: float = 1.5     # degrees, per word
    baseline_drift: float = 0.10  # fraction of em, smooth along the line
    drift_wavelength: float = 45.0  # mm per drift cycle
    tremor: float = 0.06          # mm, perpendicular wobble along strokes
    tremor_wavelength: float = 3.5  # mm per tremor cycle

    join_letters: bool = False    # draw connecting strokes within words
    resample_spacing: float = 0.6  # mm; controls tremor resolution

    def validate(self) -> None:
        if self.size <= 0:
            raise ValueError("style.size must be positive")
        if self.align not in ("left", "center", "right"):
            raise ValueError(f"unknown alignment {self.align!r}")


@dataclass
class PlacedStroke:
    points: Stroke
    char: str
    line: int
    is_join: bool = False


@dataclass
class LayoutResult:
    strokes: list[PlacedStroke]
    page: PageSetup
    line_count: int
    overflow_lines: int = 0        # lines that ran past the bottom margin
    missing: list[str] = field(default_factory=list)

    @property
    def polylines(self) -> list[Stroke]:
        return [s.points for s in self.strokes]


# --------------------------------------------------------------------------
# per-character plan
# --------------------------------------------------------------------------

@dataclass
class _CharPlan:
    """Frozen decisions for one character occurrence.

    Built before line-breaking so that measuring and placing agree exactly —
    otherwise jittered advances could push a line past the margin it was
    wrapped to fit.
    """

    char: str
    variant: Variant | None
    index: int
    scale_mul: float
    rotation: float
    dy: float
    advance: float      # already in page mm, including jitter and spacing


def _plan_characters(text: str, font: Font, style: Style, scale: float, seed: int) -> list[_CharPlan]:
    plans: list[_CharPlan] = []
    space_advance = font.metrics.space_advance * scale * style.word_spacing

    for i, ch in enumerate(text):
        if ch == "\n":
            plans.append(_CharPlan(ch, None, i, 1.0, 0.0, 0.0, 0.0))
            continue
        if ch == "\t":
            plans.append(_CharPlan(ch, None, i, 1.0, 0.0, 0.0, space_advance * 4))
            continue
        if ch.isspace():
            wobble = 1.0 + style.advance_jitter * noise.centered(seed, i, 11)
            plans.append(_CharPlan(" ", None, i, 1.0, 0.0, 0.0, space_advance * wobble))
            continue

        variants = font.variants(ch)
        if not variants:
            # Unknown character: reserve a space so the text stays readable.
            plans.append(_CharPlan(ch, None, i, 1.0, 0.0, 0.0, space_advance))
            continue

        pick = int(noise.rand(seed, i, 3) * len(variants)) % len(variants)
        variant = variants[pick]

        scale_mul = 1.0 + style.size_jitter * noise.centered(seed, i, 5)
        rotation = style.rotation_jitter * noise.centered(seed, i, 7)
        dy = style.offset_jitter * font.metrics.em * scale * noise.centered(seed, i, 9)
        adv_mul = 1.0 + style.advance_jitter * noise.centered(seed, i, 13)

        advance = variant.advance * scale * scale_mul * adv_mul + style.letter_spacing
        if i + 1 < len(text):
            advance += font.kern(ch, text[i + 1]) * scale

        plans.append(_CharPlan(ch, variant, i, scale_mul, rotation, dy, max(0.0, advance)))

    return plans


# --------------------------------------------------------------------------
# line breaking
# --------------------------------------------------------------------------

def _wrap(plans: list[_CharPlan], max_width: float) -> list[list[_CharPlan]]:
    """Greedy word wrap over already-measured characters."""
    lines: list[list[_CharPlan]] = []
    current: list[_CharPlan] = []
    word: list[_CharPlan] = []
    width = 0.0
    word_width = 0.0

    def flush_word() -> None:
        nonlocal word, word_width, current, width
        current.extend(word)
        width += word_width
        word = []
        word_width = 0.0

    def break_line() -> None:
        nonlocal current, width
        # Trailing spaces must not count toward alignment or the right margin.
        while current and current[-1].char == " ":
            current.pop()
        lines.append(current)
        current = []
        width = 0.0

    for plan in plans:
        if plan.char == "\n":
            flush_word()
            break_line()
            continue

        if plan.char in (" ", "\t"):
            flush_word()
            # A space at the start of a wrapped line is dropped, not drawn.
            if current:
                current.append(plan)
                width += plan.advance
            continue

        word.append(plan)
        word_width += plan.advance

        if width + word_width > max_width:
            if current:
                # The word fits on a line of its own: move it down whole.
                break_line()
            elif word_width > max_width:
                # A single word longer than the line: hard-break it so it
                # cannot run off the paper.
                keep = []
                acc = 0.0
                for p in word:
                    if acc + p.advance > max_width and keep:
                        break
                    keep.append(p)
                    acc += p.advance
                lines.append(keep)
                word = word[len(keep):]
                word_width = sum(p.advance for p in word)

    flush_word()
    if current:
        break_line()
    return lines or [[]]


# --------------------------------------------------------------------------
# stroke placement
# --------------------------------------------------------------------------

def _apply_tremor(stroke: Stroke, style: Style, seed: int, key: int) -> Stroke:
    """Displace points perpendicular to the stroke using smooth noise."""
    if style.tremor <= 0 or len(stroke) < 2:
        return stroke

    out: Stroke = []
    travelled = 0.0
    wl = max(0.5, style.tremor_wavelength)
    for i, p in enumerate(stroke):
        if i:
            travelled += math.dist(stroke[i - 1], p)
        # Local direction, so the offset is always across the line of travel.
        a = stroke[max(0, i - 1)]
        b = stroke[min(len(stroke) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        mag = math.hypot(dx, dy)
        if mag == 0:
            out.append(p)
            continue
        nx, ny = -dy / mag, dx / mag
        amount = style.tremor * noise.fbm(seed + key, travelled / wl, octaves=2)
        out.append((p[0] + nx * amount, p[1] + ny * amount))
    return out


def _join_stroke(exit_pt: Point, entry_pt: Point, em_mm: float) -> Stroke | None:
    """A gentle connecting curve between two letters of the same word."""
    gap = math.dist(exit_pt, entry_pt)
    if gap < 1e-6 or gap > em_mm * 0.9:
        # Too far apart to be a natural join; leave the letters separate.
        return None
    mid = ((exit_pt[0] + entry_pt[0]) / 2, (exit_pt[1] + entry_pt[1]) / 2 + gap * 0.18)
    # Quadratic through exit -> mid -> entry.
    pts: Stroke = []
    for i in range(7):
        t = i / 6
        u = 1 - t
        pts.append(
            (
                u * u * exit_pt[0] + 2 * u * t * mid[0] + t * t * entry_pt[0],
                u * u * exit_pt[1] + 2 * u * t * mid[1] + t * t * entry_pt[1],
            )
        )
    return pts


def layout_text(
    text: str,
    font: Font,
    style: Style | None = None,
    page: PageSetup | None = None,
    seed: int = 1,
) -> LayoutResult:
    """Lay ``text`` out on ``page`` in ``font``."""
    style = style or Style()
    page = page or PageSetup()
    style.validate()
    page.validate()

    if font.metrics.em <= 0:
        raise ValueError("font metrics.em must be positive")

    scale = style.size / font.metrics.em
    em_mm = style.size
    line_height = em_mm * style.line_spacing

    plans = _plan_characters(text, font, style, scale, seed)
    lines = _wrap(plans, page.content_width)

    placed: list[PlacedStroke] = []
    overflow = 0

    for line_no, line in enumerate(lines):
        line_width = sum(p.advance for p in line)
        if style.align == "center":
            x = page.margin_left + (page.content_width - line_width) / 2
        elif style.align == "right":
            x = page.margin_left + page.content_width - line_width
        else:
            x = page.margin_left

        # Baseline of the first line sits one em below the top margin, so
        # ascenders stay inside the margin rather than straddling it.
        baseline = page.margin_top + em_mm + line_no * line_height
        if baseline > page.height - page.margin_bottom:
            overflow += 1

        # Word-level drift: slant and size persist across a word.
        word_index = 0
        prev_word_char = " "

        for pos, plan in enumerate(line):
            if plan.char == " ":
                x += plan.advance
                prev_word_char = " "
                continue
            if prev_word_char == " ":
                word_index += 1
            prev_word_char = plan.char

            if plan.variant is None:
                x += plan.advance
                continue

            slant = style.slant + style.slant_jitter * noise.centered(seed, word_index, 17)
            word_size = 1.0 + style.size_jitter * 0.5 * noise.centered(seed, word_index, 19)

            drift = 0.0
            if style.baseline_drift > 0:
                wl = max(1.0, style.drift_wavelength)
                drift = (
                    style.baseline_drift
                    * em_mm
                    * noise.fbm(seed + line_no * 101, x / wl, octaves=2)
                )

            glyph_scale = scale * plan.scale_mul * word_size
            pen_y = baseline + plan.dy + drift

            # glyph space (y-up, baseline 0) -> page space (y-down)
            transform = (
                Affine.scale(glyph_scale, -glyph_scale)
                .then(Affine.rotate(plan.rotation))
                .then(Affine.skew_x(-slant))
                .then(Affine.translate(x, pen_y))
            )

            for si, stroke in enumerate(plan.variant.strokes):
                if len(stroke) < 2:
                    if len(stroke) == 1:
                        # A dot: keep it as a degenerate two-point stroke so
                        # the plotter still puts the pen down.
                        p = transform.apply(stroke[0])
                        placed.append(PlacedStroke([p, p], plan.char, line_no))
                    continue
                pts = transform.apply_stroke(stroke)
                if style.resample_spacing > 0 and stroke_length(pts) > style.resample_spacing:
                    pts = resample(pts, style.resample_spacing)
                pts = _apply_tremor(pts, style, seed, plan.index * 31 + si)
                placed.append(PlacedStroke(pts, plan.char, line_no))

            if style.join_letters and plan.variant.exit is not None:
                nxt = _next_drawable(line, pos)
                if nxt is not None and nxt.variant is not None and nxt.variant.entry is not None:
                    exit_pt = transform.apply(plan.variant.exit)
                    # Approximate the neighbour's transform by its pen origin;
                    # the join is short, so the small error is invisible.
                    entry_local = nxt.variant.entry
                    entry_pt = (
                        x + plan.advance + entry_local[0] * glyph_scale,
                        pen_y - entry_local[1] * glyph_scale,
                    )
                    join = _join_stroke(exit_pt, entry_pt, em_mm)
                    if join:
                        placed.append(PlacedStroke(join, plan.char, line_no, is_join=True))

            x += plan.advance

    return LayoutResult(
        strokes=placed,
        page=page,
        line_count=len(lines),
        overflow_lines=overflow,
        missing=font.missing(text),
    )


def _next_drawable(line: list[_CharPlan], pos: int) -> _CharPlan | None:
    """The next character in the same word, or None at a word boundary."""
    if pos + 1 >= len(line):
        return None
    nxt = line[pos + 1]
    return None if nxt.char == " " else nxt


def paginate(
    text: str,
    font: Font,
    style: Style | None = None,
    page: PageSetup | None = None,
    seed: int = 1,
) -> list[LayoutResult]:
    """Lay text out across as many pages as it needs.

    Wrapping is done once for the whole text, then lines are dealt onto
    pages, so page breaks never change how a line is broken.
    """
    style = style or Style()
    page = page or PageSetup()
    style.validate()
    page.validate()

    line_height = style.size * style.line_spacing
    per_page = max(1, int((page.content_height - style.size) // line_height) + 1)

    single = layout_text(text, font, style, page, seed)
    if single.line_count <= per_page:
        return [single]

    # Re-lay each page's slice of lines onto a fresh page.
    lines_of_text = _split_into_laid_lines(text, font, style, page, seed)
    pages: list[LayoutResult] = []
    for start in range(0, len(lines_of_text), per_page):
        chunk = "\n".join(lines_of_text[start:start + per_page])
        pages.append(layout_text(chunk, font, style, page, seed + start))
    return pages


def _split_into_laid_lines(
    text: str, font: Font, style: Style, page: PageSetup, seed: int
) -> list[str]:
    scale = style.size / font.metrics.em
    plans = _plan_characters(text, font, style, scale, seed)
    return ["".join(p.char for p in line) for line in _wrap(plans, page.content_width)]
