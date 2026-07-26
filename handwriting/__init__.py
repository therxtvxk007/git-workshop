"""handwriting-machine: turn your handwriting into pen-plotter output.

Typical use::

    from handwriting import Font, Style, PageSetup, layout_text, render

    font = Font.load("myhand.json")
    page = layout_text("hello", font, Style(size=7), PageSetup(), seed=42)
    open("out.svg", "w").write(render(page))
"""

from .font import Font, Metrics, Variant, normalise_variant
from .gcode import OutOfBounds, PlotStats, generate as generate_gcode
from .layout import LayoutResult, PageSetup, PlacedStroke, Style, layout_text, paginate
from .machine import MachineProfile
from .optimize import optimize, order_strokes
from .render_svg import render, render_strokes

__version__ = "0.1.0"

__all__ = [
    "Font",
    "Metrics",
    "Variant",
    "normalise_variant",
    "Style",
    "PageSetup",
    "PlacedStroke",
    "LayoutResult",
    "layout_text",
    "paginate",
    "MachineProfile",
    "generate_gcode",
    "PlotStats",
    "OutOfBounds",
    "optimize",
    "order_strokes",
    "render",
    "render_strokes",
    "__version__",
]
