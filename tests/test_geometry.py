import math
import unittest

from handwriting.geometry import (
    Affine,
    bbox,
    resample,
    simplify,
    smooth,
    stroke_length,
    travel_distance,
)


class TestMeasurement(unittest.TestCase):
    def test_stroke_length_sums_segments(self):
        self.assertAlmostEqual(stroke_length([(0, 0), (3, 4), (3, 9)]), 10.0)

    def test_bbox(self):
        self.assertEqual(bbox([[(1, 2), (5, 0)], [(-1, 7)]]), (-1, 0, 5, 7))

    def test_bbox_rejects_empty(self):
        with self.assertRaises(ValueError):
            bbox([])

    def test_travel_distance_measures_gaps_only(self):
        # Two 1mm strokes 5mm apart: only the gap counts.
        strokes = [[(0, 0), (1, 0)], [(6, 0), (7, 0)]]
        self.assertAlmostEqual(travel_distance(strokes), 5.0)


class TestAffine(unittest.TestCase):
    def test_translate_then_scale_order(self):
        t = Affine.translate(1, 0).then(Affine.scale(2))
        # Translate first, then scale: (0,0) -> (1,0) -> (2,0)
        self.assertEqual(t.apply((0, 0)), (2.0, 0.0))

    def test_rotate_90(self):
        x, y = Affine.rotate(90).apply((1, 0))
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 1.0)

    def test_skew_leans_with_height(self):
        # Skew must not move points on the baseline.
        skew = Affine.skew_x(20)
        self.assertAlmostEqual(skew.apply((3, 0))[0], 3.0)
        self.assertGreater(skew.apply((3, 5))[0], 3.0)

    def test_identity_roundtrip(self):
        t = Affine.scale(2).then(Affine.scale(0.5))
        self.assertAlmostEqual(t.apply((7, -3))[0], 7.0)
        self.assertAlmostEqual(t.apply((7, -3))[1], -3.0)


class TestResample(unittest.TestCase):
    def test_even_spacing(self):
        pts = resample([(0, 0), (10, 0)], 1.0)
        gaps = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        for g in gaps:
            self.assertAlmostEqual(g, 1.0, places=6)

    def test_endpoints_preserved(self):
        pts = resample([(0, 0), (2.5, 0)], 1.0)
        self.assertEqual(pts[0], (0, 0))
        self.assertAlmostEqual(pts[-1][0], 2.5)

    def test_rejects_zero_spacing(self):
        with self.assertRaises(ValueError):
            resample([(0, 0), (1, 1)], 0)

    def test_short_stroke_passes_through(self):
        self.assertEqual(resample([(1, 1)], 0.5), [(1, 1)])


class TestSimplify(unittest.TestCase):
    def test_collinear_points_dropped(self):
        straight = [(i, 0) for i in range(20)]
        self.assertEqual(simplify(straight, 0.01), [(0, 0), (19, 0)])

    def test_corner_kept(self):
        out = simplify([(0, 0), (5, 0), (5, 5)], 0.1)
        self.assertIn((5, 0), out)

    def test_tolerance_respected(self):
        # A 0.05mm bump is below a 0.1mm tolerance and should vanish.
        out = simplify([(0, 0), (1, 0.05), (2, 0)], 0.1)
        self.assertEqual(out, [(0, 0), (2, 0)])


class TestSmooth(unittest.TestCase):
    def test_endpoints_pinned(self):
        pts = smooth([(0, 0), (5, 5), (10, 0)], iterations=2)
        self.assertEqual(pts[0], (0, 0))
        self.assertEqual(pts[-1], (10, 0))

    def test_corner_is_rounded(self):
        sharp = [(0, 0), (5, 5), (10, 0)]
        rounded = smooth(sharp, iterations=1)
        # The apex should no longer reach the original corner height.
        self.assertLess(max(y for _, y in rounded), 5.0)


if __name__ == "__main__":
    unittest.main()
