import unittest

from handwriting import demo_font
from handwriting.font import Font, Variant
from handwriting.geometry import bbox
from handwriting.layout import PageSetup, Style, layout_text, paginate


def simple_font() -> Font:
    """A font of identical 5mm-wide boxes: predictable to measure."""
    font = Font("boxes")
    box = [[(0.5, 0.0), (4.5, 0.0), (4.5, 5.0), (0.5, 5.0), (0.5, 0.0)]]
    for ch in "abcdefghijklmnopqrstuvwxyz":
        font.add(ch, Variant([list(box[0])], 5.0, (0.5, 0.0), (4.5, 0.0)))
    return font


STEADY = Style(
    size_jitter=0, rotation_jitter=0, offset_jitter=0, advance_jitter=0,
    slant_jitter=0, baseline_drift=0, tremor=0,
)


class TestBasics(unittest.TestCase):
    def setUp(self):
        self.font = demo_font.build()

    def test_produces_strokes(self):
        result = layout_text("hello", self.font, STEADY)
        self.assertTrue(result.strokes)
        self.assertEqual(result.line_count, 1)

    def test_empty_text_is_not_an_error(self):
        result = layout_text("", self.font, STEADY)
        self.assertEqual(result.strokes, [])

    def test_whitespace_only_text(self):
        result = layout_text("   ", self.font, STEADY)
        self.assertEqual(result.strokes, [])

    def test_unknown_characters_are_reported_not_drawn(self):
        result = layout_text("aéb", self.font, STEADY)
        self.assertEqual(result.missing, ["é"])
        self.assertTrue(result.strokes)  # a and b still drawn

    def test_rejects_bad_alignment(self):
        with self.assertRaises(ValueError):
            layout_text("x", self.font, Style(align="middle"))

    def test_rejects_impossible_margins(self):
        page = PageSetup(width=50, height=50, margin_left=30, margin_right=30)
        with self.assertRaises(ValueError):
            layout_text("x", self.font, STEADY, page)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_gives_identical_output(self):
        font = demo_font.build()
        a = layout_text("the quick brown fox", font, Style(), seed=7)
        b = layout_text("the quick brown fox", font, Style(), seed=7)
        self.assertEqual(a.polylines, b.polylines)

    def test_different_seeds_differ(self):
        font = demo_font.build()
        a = layout_text("the quick brown fox", font, Style(), seed=7)
        b = layout_text("the quick brown fox", font, Style(), seed=8)
        self.assertNotEqual(a.polylines, b.polylines)

    def test_variation_can_be_switched_off(self):
        """With no jitter, a repeated letter must be drawn identically."""
        font = simple_font()
        result = layout_text("aa", font, STEADY)
        first, second = result.polylines[0], result.polylines[1]
        dx = second[0][0] - first[0][0]
        shifted = [(x + dx, y) for x, y in first]
        for p, q in zip(shifted, second):
            self.assertAlmostEqual(p[0], q[0], places=6)
            self.assertAlmostEqual(p[1], q[1], places=6)


class TestMargins(unittest.TestCase):
    def test_text_stays_inside_the_content_box(self):
        font = demo_font.build()
        page = PageSetup()
        text = "The machine writes whatever you give it, wrapping as needed. " * 4
        result = layout_text(text, font, Style(size=6), page, seed=3)

        min_x, min_y, max_x, max_y = bbox(result.polylines)
        # Jitter is allowed to nudge glyphs slightly past the guide, but not
        # off the paper.
        self.assertGreater(min_x, 0)
        self.assertLess(max_x, page.width)
        self.assertGreater(min_y, 0)
        self.assertLess(max_y, page.height)

    def test_right_margin_respected_without_jitter(self):
        font = simple_font()
        page = PageSetup()
        text = "aaa bbb ccc ddd eee fff ggg hhh iii jjj kkk lll mmm nnn ooo"
        result = layout_text(text, font, STEADY, page)
        max_x = bbox(result.polylines)[2]
        self.assertLessEqual(max_x, page.width - page.margin_right + 0.01)

    def test_long_unbreakable_word_is_hard_wrapped(self):
        font = simple_font()
        page = PageSetup(width=100, height=200, margin_left=10, margin_right=10)
        result = layout_text("a" * 60, font, STEADY, page)
        self.assertGreater(result.line_count, 1)
        self.assertLessEqual(bbox(result.polylines)[2], page.width - page.margin_right + 0.01)


class TestWrapping(unittest.TestCase):
    def test_explicit_newlines_break_lines(self):
        result = layout_text("a\nb\nc", demo_font.build(), STEADY)
        self.assertEqual(result.line_count, 3)

    def test_wrapping_creates_lines(self):
        font = simple_font()
        page = PageSetup(width=100, height=200, margin_left=10, margin_right=10)
        # 80mm of content width fits 16 boxes per line.
        result = layout_text(" ".join(["ab"] * 20), font, STEADY, page)
        self.assertGreater(result.line_count, 1)

    def test_lines_are_stacked_downward(self):
        font = simple_font()
        result = layout_text("a\nb", font, STEADY)
        first = [s for s in result.strokes if s.line == 0][0]
        second = [s for s in result.strokes if s.line == 1][0]
        self.assertGreater(second.points[0][1], first.points[0][1])

    def test_overflow_is_reported(self):
        font = simple_font()
        page = PageSetup(width=100, height=60, margin_top=10, margin_bottom=10)
        result = layout_text("\n".join("a" * 1 for _ in range(20)), font, STEADY, page)
        self.assertGreater(result.overflow_lines, 0)


class TestAlignment(unittest.TestCase):
    def _extent(self, align):
        font = simple_font()
        page = PageSetup()
        style = Style(**{**STEADY.__dict__, "align": align})
        result = layout_text("aaa", font, style, page)
        return bbox(result.polylines)

    def test_left_starts_at_the_margin(self):
        # Left margin 20mm, plus the box's own 0.5 unit bearing at 0.6 scale.
        self.assertAlmostEqual(self._extent("left")[0], 20.3, places=1)

    def test_right_ends_at_the_margin(self):
        self.assertLess(abs(self._extent("right")[2] - 189.5), 1.0)

    def test_center_is_between_the_two(self):
        left = self._extent("left")[0]
        center = self._extent("center")[0]
        right = self._extent("right")[0]
        self.assertLess(left, center)
        self.assertLess(center, right)


class TestStyleControls(unittest.TestCase):
    def test_size_scales_the_output(self):
        font = demo_font.build()
        small = bbox(layout_text("mmm", font, Style(**{**STEADY.__dict__, "size": 4})).polylines)
        large = bbox(layout_text("mmm", font, Style(**{**STEADY.__dict__, "size": 8})).polylines)
        self.assertGreater(large[2] - large[0], (small[2] - small[0]) * 1.8)

    def test_slant_leans_ascenders_right(self):
        font = simple_font()
        upright = layout_text("a", font, Style(**{**STEADY.__dict__, "slant": 0})).polylines
        leaning = layout_text("a", font, Style(**{**STEADY.__dict__, "slant": 20})).polylines
        # The box's top edge moves right while its baseline edge stays put,
        # so the glyph gets wider without shifting its left foot.
        self.assertAlmostEqual(bbox(upright)[0], bbox(leaning)[0], places=3)
        self.assertGreater(bbox(leaning)[2], bbox(upright)[2] + 0.5)

    def test_letter_spacing_widens_the_line(self):
        font = simple_font()
        tight = bbox(layout_text("aaaa", font, STEADY).polylines)
        loose_style = Style(**{**STEADY.__dict__, "letter_spacing": 2.0})
        loose = bbox(layout_text("aaaa", font, loose_style).polylines)
        self.assertGreater(loose[2] - loose[0], tight[2] - tight[0])

    def test_line_spacing_changes_page_depth(self):
        font = simple_font()
        tight = bbox(layout_text("a\na\na", font, STEADY).polylines)
        wide_style = Style(**{**STEADY.__dict__, "line_spacing": 3.5})
        wide = bbox(layout_text("a\na\na", font, wide_style).polylines)
        self.assertGreater(wide[3] - wide[1], tight[3] - tight[1])

    def test_tremor_perturbs_but_does_not_displace(self):
        font = simple_font()
        steady = layout_text("a", font, STEADY).polylines[0]
        shaky_style = Style(**{**STEADY.__dict__, "tremor": 0.3})
        shaky = layout_text("a", font, shaky_style).polylines[0]
        self.assertNotEqual(steady, shaky)
        # The letter should stay roughly where it was.
        self.assertLess(abs(bbox([shaky])[0] - bbox([steady])[0]), 1.0)

    def test_joins_add_extra_strokes(self):
        font = simple_font()
        plain = layout_text("aaa", font, STEADY)
        joined_style = Style(**{**STEADY.__dict__, "join_letters": True})
        joined = layout_text("aaa", font, joined_style)
        self.assertGreater(len(joined.strokes), len(plain.strokes))
        self.assertTrue(any(s.is_join for s in joined.strokes))


class TestPagination(unittest.TestCase):
    def test_short_text_is_one_page(self):
        pages = paginate("hello", demo_font.build(), Style())
        self.assertEqual(len(pages), 1)

    def test_long_text_spills_onto_more_pages(self):
        text = ("Every page of this letter is written by a machine holding a real pen. " * 40)
        pages = paginate(text, demo_font.build(), Style(size=6))
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertLess(bbox(page.polylines)[3], page.page.height)

    def test_no_page_overflows_its_bottom_margin(self):
        text = "line\n" * 120
        pages = paginate(text, demo_font.build(), Style(size=6))
        for page in pages:
            self.assertEqual(page.overflow_lines, 0)


if __name__ == "__main__":
    unittest.main()
