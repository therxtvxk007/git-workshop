"""The browser capture tool is the only part of the pipeline written in
JavaScript, so what it exports is a contract.  ``captured-abc.json`` is a real
export from ``capture/index.html`` — three letters drawn with a mouse — and
these tests pin the shape and the conventions of that file.

If a change to the capture tool breaks one of these, the tool is wrong: every
font a user has already recorded is in this format.
"""

import json
import unittest
from pathlib import Path

from handwriting.font import Font
from handwriting.gcode import generate
from handwriting.layout import PageSetup, Style, layout_text
from handwriting.machine import MachineProfile

FIXTURE = Path(__file__).parent / "fixtures" / "captured-abc.json"


class TestCaptureExport(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.font = Font.load(FIXTURE)

    def test_declares_the_expected_format(self):
        self.assertEqual(self.raw["format"], "handwriting-machine/font")
        self.assertEqual(self.raw["units"], "mm")
        self.assertEqual(self.raw["metrics"]["em"], 10.0)

    def test_loads_as_a_font(self):
        self.assertEqual(sorted(self.font.glyphs), ["a", "b", "c"])
        for ch in "abc":
            self.assertTrue(self.font.variant(ch, 0).strokes)

    def test_baseline_is_at_zero_and_y_points_up(self):
        """'b' has an ascender, so it must reach well above the x-height."""
        b = self.font.variant("b", 0)
        highest = max(y for stroke in b.strokes for _, y in stroke)
        self.assertGreater(highest, self.font.metrics.x_height)
        lowest = min(y for stroke in b.strokes for _, y in stroke)
        self.assertAlmostEqual(lowest, 0.0, delta=0.5)

    def test_glyphs_are_shifted_to_a_left_side_bearing(self):
        for ch in "abc":
            left = min(x for stroke in self.font.variant(ch, 0).strokes for x, _ in stroke)
            self.assertAlmostEqual(left, 0.35, delta=0.01)

    def test_advance_exceeds_the_ink_width(self):
        for ch in "abc":
            v = self.font.variant(ch, 0)
            right = max(x for stroke in v.strokes for x, _ in stroke)
            self.assertGreater(v.advance, right)

    def test_entry_and_exit_are_stroke_endpoints(self):
        for ch in "abc":
            v = self.font.variant(ch, 0)
            self.assertEqual(tuple(v.entry), tuple(v.strokes[0][0]))
            self.assertEqual(tuple(v.exit), tuple(v.strokes[-1][-1]))

    def test_plots_all_the_way_to_gcode(self):
        result = layout_text("abc cab", self.font, Style(), PageSetup(), seed=2)
        self.assertEqual(result.missing, [])
        text, stats = generate(
            result.polylines,
            MachineProfile(name="t", bed_width=210, bed_height=297),
            page_height=result.page.height,
        )
        self.assertGreater(stats.strokes, 5)
        self.assertIn("G1 ", text)


if __name__ == "__main__":
    unittest.main()
