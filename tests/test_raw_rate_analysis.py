import unittest

from raw_rate_analysis import RawWorkload, classify_workload, suggested_rate


class RawRateAnalysisTests(unittest.TestCase):
    def test_light_chapter_uses_minimum(self):
        label, level, _ = classify_workload(RawWorkload(12, 12, 48_000, 4_000, 0))
        self.assertEqual((label, suggested_rate(4_000, 8_000, level)), ("Ringan", 4_000))

    def test_tall_images_raise_workload(self):
        label, level, _ = classify_workload(RawWorkload(16, 16, 140_000, 11_000, 3))
        self.assertEqual(label, "Berat")
        self.assertEqual(suggested_rate(5_000, 10_000, level), 10_000)

    def test_medium_uses_rounded_midpoint(self):
        _label, level, _ = classify_workload(RawWorkload(20, 20, 120_000, 6_000, 0))
        self.assertEqual(suggested_rate(9_000, 18_000, level), 13_500)
