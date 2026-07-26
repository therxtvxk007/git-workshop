import re
import tempfile
import unittest
from pathlib import Path

from handwriting import demo_font
from handwriting.gcode import OutOfBounds, generate, to_machine
from handwriting.layout import PageSetup, Style, layout_text
from handwriting.machine import MachineProfile
from handwriting.optimize import optimize, order_strokes
from handwriting.render_svg import render
from handwriting.sender import clean_lines


def a4_profile() -> MachineProfile:
    return MachineProfile(name="test", bed_width=210, bed_height=297)


class TestOptimize(unittest.TestCase):
    def test_travel_is_reduced(self):
        # Strokes deliberately ordered to zig-zag across the page.
        strokes = [
            [(0, 0), (1, 0)],
            [(100, 100), (101, 100)],
            [(2, 0), (3, 0)],
            [(102, 100), (103, 100)],
        ]
        ordered, before, after = optimize(strokes)
        self.assertLess(after, before)
        self.assertEqual(len(ordered), 4)

    def test_no_strokes_are_lost(self):
        strokes = [[(i, 0), (i + 1, 5)] for i in range(30)]
        ordered = order_strokes(strokes)
        self.assertEqual(len(ordered), 30)
        # Every original stroke survives, in one direction or the other.
        originals = {frozenset(map(tuple, s)) for s in strokes}
        result = {frozenset(map(tuple, s)) for s in ordered}
        self.assertEqual(originals, result)

    def test_reversal_can_be_disabled(self):
        strokes = [[(0, 0), (10, 0)], [(9, 0), (1, 0)]]
        ordered = order_strokes(strokes, allow_reverse=False)
        self.assertEqual(ordered[1][0], (9, 0))

    def test_degenerate_strokes_dropped(self):
        ordered, _, _ = optimize([[(0, 0)], [(1, 1), (2, 2)]])
        self.assertEqual(len(ordered), 1)

    def test_never_worse_than_the_original_order(self):
        # A single line of text is already near-optimal in reading order;
        # a greedy tour must not be allowed to make it worse.
        strokes = [[(x, 0), (x + 2, 0)] for x in range(0, 60, 3)]
        ordered, before, after = optimize(strokes)
        self.assertLessEqual(after, before)
        self.assertEqual(ordered, [[(x, 0), (x + 2, 0)] for x in range(0, 60, 3)])

    def test_still_improves_a_scattered_page(self):
        strokes = []
        for i in range(12):
            strokes.append([(0, i * 10), (5, i * 10)])
            strokes.append([(150, i * 10), (155, i * 10)])
        _, before, after = optimize(strokes)
        self.assertLess(after, before * 0.6)


class TestGcode(unittest.TestCase):
    def setUp(self):
        self.profile = a4_profile()

    def test_structure(self):
        text, stats = generate([[(10, 10), (20, 10)]], self.profile, page_height=297)
        self.assertIn("G21", text)
        self.assertIn("G0 ", text)
        self.assertIn("G1 ", text)
        self.assertEqual(stats.strokes, 1)
        self.assertAlmostEqual(stats.draw_mm, 10.0)

    def test_pen_is_lifted_before_every_travel(self):
        strokes = [[(10, 10), (20, 10)], [(50, 50), (60, 60)]]
        text, _ = generate(strokes, self.profile, page_height=297)
        lines = [l for l in text.splitlines() if l.startswith(("G0 ", "G1 ")) or l.startswith("M3")]

        pen_down = False
        for line in lines:
            if line == self.profile.pen_down[0]:
                pen_down = True
            elif line == self.profile.pen_up[0]:
                pen_down = False
            elif line.startswith("G0 "):
                self.assertFalse(pen_down, "rapid travel while the pen is down")

    def test_pen_ends_up(self):
        text, _ = generate([[(10, 10), (20, 10)]], self.profile, page_height=297)
        commands = [l for l in text.splitlines() if l in ("M3 S0", "M3 S90")]
        self.assertEqual(commands[-1], "M3 S0")

    def test_y_is_flipped_into_machine_space(self):
        # Page y=0 is the top of the paper, which is the far edge of the bed.
        self.assertEqual(to_machine((10, 0), self.profile, 297)[1], 297)
        self.assertEqual(to_machine((10, 297), self.profile, 297)[1], 0)

    def test_flip_can_be_disabled(self):
        profile = a4_profile()
        profile.flip_y = False
        self.assertEqual(to_machine((10, 5), profile, 297)[1], 5)

    def test_origin_offset_applied(self):
        profile = a4_profile()
        profile.origin_x, profile.origin_y = 5.0, 7.0
        x, y = to_machine((10, 297), profile, 297)
        self.assertEqual((x, y), (15.0, 7.0))

    def test_out_of_bounds_raises_before_writing(self):
        profile = MachineProfile(name="small", bed_width=50, bed_height=50)
        with self.assertRaises(OutOfBounds):
            generate([[(10, 10), (400, 10)]], profile, page_height=50)

    def test_bounds_check_can_be_waived(self):
        profile = MachineProfile(name="small", bed_width=50, bed_height=50)
        text, _ = generate([[(10, 10), (400, 10)]], profile, page_height=50, check_bounds=False)
        self.assertIn("G1 ", text)

    def test_coordinates_respect_precision(self):
        profile = a4_profile()
        profile.precision = 2
        text, _ = generate([[(10.123456, 10), (20, 10)]], profile, page_height=297)
        for value in re.findall(r"[XY](-?\d+\.\d+)", text):
            self.assertLessEqual(len(value.split(".")[1]), 2)

    def test_real_page_fits_a4_machine(self):
        font = demo_font.build()
        result = layout_text("Dear friend,\n\nThis was written by a machine.", font, Style(), seed=5)
        text, stats = generate(result.polylines, self.profile, page_height=result.page.height)
        self.assertGreater(stats.strokes, 10)
        self.assertGreater(stats.estimate_minutes(self.profile), 0)


class TestMachineProfile(unittest.TestCase):
    def test_load_from_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.toml"
            path.write_text(
                '[machine]\nname = "x"\nbed_width = 100\nbed_height = 100\n'
                'pen_up = ["A"]\npen_down = ["B"]\n'
            )
            profile = MachineProfile.load(path)
        self.assertEqual(profile.name, "x")
        self.assertEqual(profile.pen_up, ["A"])

    def test_shipped_profiles_are_valid(self):
        for path in sorted((Path(__file__).parent.parent / "machines").glob("*.toml")):
            with self.subTest(profile=path.name):
                MachineProfile.load(path).validate()

    def test_unknown_key_is_rejected(self):
        # A typo in a profile should be loud, not silently ignored.
        with self.assertRaises(ValueError):
            MachineProfile.from_dict({"bed_wdith": 100})

    def test_invalid_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            MachineProfile.from_dict({"bed_width": 0})


class TestSvg(unittest.TestCase):
    def test_wellformed_and_sized_in_mm(self):
        result = layout_text("hi", demo_font.build(), Style(), seed=1)
        svg = render(result)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn('width="210mm"', svg)
        self.assertIn('viewBox="0 0 210 297"', svg)
        self.assertIn("<path", svg)

    def test_empty_page_still_valid(self):
        result = layout_text("", demo_font.build(), Style())
        svg = render(result)
        self.assertIn("</svg>", svg)
        self.assertNotIn("<path", svg)

    def test_optional_overlays(self):
        result = layout_text("hi there", demo_font.build(), Style())
        svg = render(result, show_margins=True, show_travel=True)
        self.assertIn("stroke-dasharray", svg)


class TestSender(unittest.TestCase):
    def test_comments_and_blanks_are_stripped(self):
        gcode = "; header\nG21\n\nG0 X1 Y2 ; move\n"
        self.assertEqual(list(clean_lines(gcode)), ["G21", "G0 X1 Y2"])


if __name__ == "__main__":
    unittest.main()
