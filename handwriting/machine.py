"""Machine profiles.

Every plotter lifts its pen differently — a hobby servo on a spare GRBL pin,
a Z axis, an M280 on Marlin.  Rather than guess, a profile just carries the
literal G-code lines to emit for pen up and pen down, so any machine can be
described without changing code.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MachineProfile:
    name: str = "generic-grbl-servo"

    # Drawable area, millimetres, measured from the machine origin.
    bed_width: float = 200.0
    bed_height: float = 280.0

    # Where the top-left of the paper sits in machine coordinates.
    origin_x: float = 0.0
    origin_y: float = 0.0

    # Machine Y usually grows away from the operator while page Y grows
    # downward, so the page is flipped by default.
    flip_y: bool = True

    feed_draw: float = 1800.0     # mm/min with the pen down
    feed_travel: float = 4000.0   # mm/min with the pen up

    pen_up: list[str] = field(default_factory=lambda: ["M3 S0"])
    pen_down: list[str] = field(default_factory=lambda: ["M3 S90"])
    pen_up_dwell: float = 0.12    # seconds; let the servo actually arrive
    pen_down_dwell: float = 0.12

    header: list[str] = field(default_factory=lambda: ["G21", "G90", "G94"])
    footer: list[str] = field(default_factory=lambda: ["G0 X0 Y0"])

    precision: int = 3

    def validate(self) -> None:
        if self.bed_width <= 0 or self.bed_height <= 0:
            raise ValueError("bed dimensions must be positive")
        if self.feed_draw <= 0 or self.feed_travel <= 0:
            raise ValueError("feed rates must be positive")
        if not self.pen_up or not self.pen_down:
            raise ValueError("profile must define both pen_up and pen_down commands")

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MachineProfile":
        known = MachineProfile.__dataclass_fields__
        unknown = sorted(set(d) - set(known))
        if unknown:
            raise ValueError(f"unknown machine profile key(s): {', '.join(unknown)}")
        profile = MachineProfile(**{k: v for k, v in d.items() if k in known})
        profile.validate()
        return profile

    @staticmethod
    def load(path: str | Path) -> "MachineProfile":
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        # Allow either a flat file or a [machine] table.
        return MachineProfile.from_dict(data.get("machine", data))
