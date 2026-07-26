"""G-code generation.

Page coordinates (mm, y-down, origin top-left of the paper) are converted to
machine coordinates and emitted as G0 travels and G1 draws, with the profile's
pen commands between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .geometry import Point, Stroke, stroke_length, travel_distance
from .machine import MachineProfile


class OutOfBounds(ValueError):
    """A stroke falls outside the machine's drawable area."""


@dataclass
class PlotStats:
    strokes: int
    points: int
    draw_mm: float
    travel_mm: float
    pen_lifts: float

    def estimate_minutes(self, profile: MachineProfile) -> float:
        """Rough plot time. Ignores acceleration, so treat it as a floor."""
        drawing = self.draw_mm / profile.feed_draw
        travelling = self.travel_mm / profile.feed_travel
        dwell = self.pen_lifts * (profile.pen_up_dwell + profile.pen_down_dwell) / 60.0
        return drawing + travelling + dwell

    def describe(self, profile: MachineProfile) -> str:
        return (
            f"{self.strokes} strokes, {self.points} points, "
            f"{self.draw_mm:.0f}mm drawn, {self.travel_mm:.0f}mm travel, "
            f"~{self.estimate_minutes(profile):.1f} min"
        )


def to_machine(p: Point, profile: MachineProfile, page_height: float) -> Point:
    x = profile.origin_x + p[0]
    y = (page_height - p[1]) if profile.flip_y else p[1]
    return (x, profile.origin_y + y)


def generate(
    strokes: Sequence[Stroke],
    profile: MachineProfile,
    page_height: float,
    page_width: float | None = None,
    title: str = "",
    check_bounds: bool = True,
) -> tuple[str, PlotStats]:
    """Render ``strokes`` to a G-code program.

    ``check_bounds`` raises rather than letting the machine slam a rail; pass
    ``False`` only if you know the profile's bed size is wrong.
    """
    profile.validate()
    fmt = f"{{:.{profile.precision}f}}"
    lines: list[str] = []

    def emit(line: str) -> None:
        lines.append(line)

    drawable = [list(s) for s in strokes if len(s) >= 2]

    # Fail before emitting anything, so a bad file is never half-written.
    if check_bounds:
        _check_bounds(drawable, profile, page_height)

    if title:
        emit(f"; {title}")
    emit(f"; machine: {profile.name}")
    emit(f"; strokes: {len(drawable)}")
    for line in profile.header:
        emit(line)

    pen_is_down = False

    def pen_up() -> None:
        nonlocal pen_is_down
        for cmd in profile.pen_up:
            emit(cmd)
        if profile.pen_up_dwell > 0:
            emit(f"G4 P{profile.pen_up_dwell:g}")
        pen_is_down = False

    def pen_down() -> None:
        nonlocal pen_is_down
        for cmd in profile.pen_down:
            emit(cmd)
        if profile.pen_down_dwell > 0:
            emit(f"G4 P{profile.pen_down_dwell:g}")
        pen_is_down = True

    pen_up()

    draw_mm = 0.0
    points = 0
    for stroke in drawable:
        machine_pts = [to_machine(p, profile, page_height) for p in stroke]
        start = machine_pts[0]
        emit(f"G0 X{fmt.format(start[0])} Y{fmt.format(start[1])} F{profile.feed_travel:g}")
        pen_down()
        for p in machine_pts[1:]:
            emit(f"G1 X{fmt.format(p[0])} Y{fmt.format(p[1])} F{profile.feed_draw:g}")
        pen_up()
        draw_mm += stroke_length(stroke)
        points += len(stroke)

    for line in profile.footer:
        emit(line)

    stats = PlotStats(
        strokes=len(drawable),
        points=points,
        draw_mm=draw_mm,
        travel_mm=travel_distance(drawable),
        pen_lifts=len(drawable),
    )
    return "\n".join(lines) + "\n", stats


def _check_bounds(
    strokes: Iterable[Sequence[Point]], profile: MachineProfile, page_height: float
) -> None:
    lo_x = lo_y = float("inf")
    hi_x = hi_y = float("-inf")
    for stroke in strokes:
        for p in stroke:
            mx, my = to_machine(p, profile, page_height)
            lo_x, hi_x = min(lo_x, mx), max(hi_x, mx)
            lo_y, hi_y = min(lo_y, my), max(hi_y, my)
    if lo_x == float("inf"):
        return

    tol = 1e-6
    if lo_x < -tol or lo_y < -tol or hi_x > profile.bed_width + tol or hi_y > profile.bed_height + tol:
        raise OutOfBounds(
            f"drawing spans X {lo_x:.1f}..{hi_x:.1f}, Y {lo_y:.1f}..{hi_y:.1f} mm, "
            f"outside the {profile.bed_width:g} x {profile.bed_height:g} mm bed of "
            f"'{profile.name}'. Adjust margins, --size, or the profile's origin."
        )
