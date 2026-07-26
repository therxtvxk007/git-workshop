import json
import tempfile
import unittest
from pathlib import Path

from handwriting import demo_font
from handwriting.font import Font, Metrics, Variant, normalise_variant


class TestSerialisation(unittest.TestCase):
    def test_roundtrip_preserves_geometry(self):
        font = Font("test", Metrics())
        font.add("a", Variant([[(0.0, 0.0), (1.0, 2.0)]], 3.0, (0.0, 0.0), (1.0, 2.0)))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            font.save(path)
            loaded = Font.load(path)

        variant = loaded.variant("a", 0)
        self.assertEqual(variant.strokes, [[(0.0, 0.0), (1.0, 2.0)]])
        self.assertEqual(variant.advance, 3.0)
        self.assertEqual(variant.exit, (1.0, 2.0))

    def test_bare_single_stroke_accepted_as_one_variant(self):
        # Hand-authored files should not need the full variant wrapper.
        font = Font.from_dict({"glyphs": {"x": [[[0, 0], [1, 1]]]}})
        self.assertEqual(len(font.variants("x")), 1)
        self.assertEqual(font.variant("x", 0).strokes, [[(0.0, 0.0), (1.0, 1.0)]])
        self.assertGreater(font.variant("x", 0).advance, 0)

    def test_bare_multi_stroke_list_accepted(self):
        font = Font.from_dict({"glyphs": {"t": [[[[0, 0], [0, 5]], [[-1, 3], [1, 3]]]]}})
        self.assertEqual(len(font.variants("t")), 1)
        self.assertEqual(len(font.variant("t", 0).strokes), 2)

    def test_malformed_glyph_is_rejected(self):
        with self.assertRaises(ValueError):
            Font.from_dict({"glyphs": {"x": [[0, 0]]}})

    def test_rejects_foreign_format(self):
        with self.assertRaises(ValueError):
            Font.from_dict({"format": "something/else", "glyphs": {}})

    def test_demo_font_survives_roundtrip(self):
        original = demo_font.build()
        restored = Font.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(sorted(restored.glyphs), sorted(original.glyphs))


class TestLookup(unittest.TestCase):
    def test_variant_index_wraps(self):
        font = Font()
        font.add("a", Variant([[(0, 0), (1, 1)]], 2.0))
        font.add("a", Variant([[(0, 0), (2, 2)]], 2.0))
        self.assertIs(font.variant("a", 0), font.variant("a", 2))
        self.assertIs(font.variant("a", 1), font.variant("a", 3))

    def test_missing_reports_unknown_characters_once(self):
        font = demo_font.build()
        self.assertEqual(font.missing("ok ok"), [])
        self.assertEqual(font.missing("aééb"), ["é"])

    def test_missing_ignores_whitespace(self):
        self.assertEqual(demo_font.build().missing("a b\tc\nd"), [])


class TestMaintenance(unittest.TestCase):
    def test_merge_accumulates_variants(self):
        a = Font("a")
        a.add("x", Variant([[(0, 0), (1, 1)]], 2.0))
        b = Font("b")
        b.add("x", Variant([[(0, 0), (2, 2)]], 2.0))
        b.add("y", Variant([[(0, 0), (1, 0)]], 2.0))

        a.merge(b)
        self.assertEqual(len(a.variants("x")), 2)
        self.assertEqual(len(a.variants("y")), 1)

    def test_clean_reduces_point_count(self):
        font = Font()
        # A straight line captured with far too many samples.
        font.add("l", Variant([[(0.0, float(i) / 10) for i in range(200)]], 2.0))
        before = len(font.variant("l", 0).strokes[0])
        font.clean(tolerance=0.05, smooth_passes=0)
        after = len(font.variant("l", 0).strokes[0])
        self.assertLess(after, before / 10)

    def test_summary_flags_single_variant_characters(self):
        font = Font()
        font.add("q", Variant([[(0, 0), (1, 1)]], 2.0))
        self.assertIn("only one variant", font.summary())


class TestNormalise(unittest.TestCase):
    def test_flips_y_and_places_left_bearing(self):
        # Capture space is y-down with the baseline at y=100.
        variant = normalise_variant(
            [[(50.0, 100.0), (50.0, 50.0)]],
            baseline_y=100.0,
            unit_scale=0.1,
            side_bearing=0.35,
        )
        self.assertAlmostEqual(variant.strokes[0][0][1], 0.0)   # on the baseline
        self.assertAlmostEqual(variant.strokes[0][1][1], 5.0)   # 50px above -> +5 units
        self.assertAlmostEqual(variant.strokes[0][0][0], 0.35)  # shifted to the bearing

    def test_advance_covers_ink_plus_bearings(self):
        variant = normalise_variant(
            [[(0.0, 10.0), (10.0, 10.0)]], baseline_y=10.0, unit_scale=1.0, side_bearing=0.5
        )
        self.assertAlmostEqual(variant.advance, 11.0)  # 10 wide + 0.5 either side

    def test_empty_input_is_harmless(self):
        self.assertEqual(normalise_variant([], 0, 1).strokes, [])


class TestDemoFont(unittest.TestCase):
    def setUp(self):
        self.font = demo_font.build()

    def test_covers_printable_ascii_basics(self):
        for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            self.assertTrue(self.font.has(ch), f"missing {ch!r}")

    def test_every_glyph_has_ink_and_advance(self):
        for ch, variants in self.font.glyphs.items():
            for v in variants:
                self.assertTrue(v.strokes, f"{ch!r} has no strokes")
                self.assertGreater(v.advance, 0, f"{ch!r} has no advance")
                for stroke in v.strokes:
                    self.assertGreaterEqual(len(stroke), 1)

    def test_glyphs_sit_within_sane_vertical_bounds(self):
        m = self.font.metrics
        for ch, variants in self.font.glyphs.items():
            for v in variants:
                for stroke in v.strokes:
                    for _, y in stroke:
                        self.assertGreaterEqual(y, m.descender - 0.5, f"{ch!r} drops too low")
                        self.assertLessEqual(y, m.ascender + 0.5, f"{ch!r} rises too high")

    def test_glyphs_start_at_positive_x(self):
        for ch, variants in self.font.glyphs.items():
            for v in variants:
                for stroke in v.strokes:
                    for x, _ in stroke:
                        self.assertGreaterEqual(x, -1.0, f"{ch!r} starts left of the origin")


if __name__ == "__main__":
    unittest.main()
