"""Tests for windowing and trend classification."""

import unittest

from rbn_tracker.processing import (
    FADING,
    GONE,
    NEW,
    RISING,
    STEADY,
    SpotProcessor,
    classify_horizon,
    classify_trend,
    windows_for_secs,
)
from rbn_tracker.spots import parse_spot


def spot(spotter, dx, freq, snr, t, wpm=28):
    line = f"DX de {spotter}: {freq} {dx} CW {snr} dB {wpm} wpm CQ 1200Z"
    return parse_spot(line, recv_time=t)


class TestTrend(unittest.TestCase):
    def test_new(self):
        self.assertEqual(classify_trend([0, 0, 5]), NEW)
        self.assertEqual(classify_trend([3]), NEW)

    def test_gone(self):
        self.assertEqual(classify_trend([5, 4, 0]), GONE)

    def test_rising(self):
        self.assertEqual(classify_trend([3, 5, 8]), RISING)

    def test_fading(self):
        self.assertEqual(classify_trend([10, 9, 5]), FADING)

    def test_steady(self):
        self.assertEqual(classify_trend([8, 8, 8]), STEADY)
        self.assertEqual(classify_trend([8, 9, 9]), STEADY)


class TestHorizonTrend(unittest.TestCase):
    def test_windows_for_secs(self):
        self.assertEqual(windows_for_secs(600, 60), 10)
        self.assertEqual(windows_for_secs(1800, 60), 30)
        self.assertEqual(windows_for_secs(3600, 60), 60)
        self.assertEqual(windows_for_secs(600, 300), 2)  # never below 2

    def test_rising_over_horizon(self):
        # Older half low, newer half high.
        self.assertEqual(classify_horizon([1, 1, 2, 5, 6, 7], 6), RISING)

    def test_fading_over_horizon(self):
        self.assertEqual(classify_horizon([8, 7, 6, 2, 1, 1], 6), FADING)

    def test_steady_over_horizon(self):
        self.assertEqual(classify_horizon([5, 6, 5, 6, 5, 6], 6), STEADY)

    def test_new_over_horizon(self):
        self.assertEqual(classify_horizon([0, 0, 0, 4, 5, 6], 6), NEW)

    def test_gone_over_horizon(self):
        self.assertEqual(classify_horizon([6, 5, 6, 0, 0, 0], 6), GONE)

    def test_uses_only_last_n_windows(self):
        # A big early spike is outside the 2-window horizon -> ignored.
        self.assertEqual(classify_horizon([50, 1, 1], 2), STEADY)


class TestWindowing(unittest.TestCase):
    def test_window_keyed_on_recv_time(self):
        proc = SpotProcessor(mycall="MM1E", window_secs=60, history=5)
        # Two spots inside window, one stale.
        proc.add(spot("W3LPL-#", "G4ABC", 21025, 15, t=5))
        proc.add(spot("K1TTT-#", "MM1E", 21030, 20, t=50))
        proc.add(spot("DL8TG-#", "M0TTT", 14036, 10, t=200))  # later window

        s1 = proc.roll(now=60)  # window (0,60]
        self.assertEqual(s1.total_spots, 2)
        self.assertEqual(s1.total_uk_spots, 2)
        self.assertTrue(s1.mm_spotted)  # MM1E heard
        self.assertIn("15m", s1.active_bands())

    def test_distinct_counts_and_mm(self):
        proc = SpotProcessor(mycall="MM1E", window_secs=60, history=5)
        proc.add(spot("W3LPL-#", "MM1E", 21025, 18, t=1))
        proc.add(spot("K1TTT-#", "MM1E", 21025, 22, t=2))
        proc.add(spot("W3LPL-#", "MM1E", 21025, 19, t=3))  # dup spotter
        s = proc.roll(now=60)
        self.assertEqual(s.mm_band_spotters("15m"), 2)  # W3LPL + K1TTT
        obs = s.mm[("15m", "NA")]
        self.assertEqual(obs.distinct_spotters, 2)
        self.assertEqual(obs.best_snr, 22)

    def test_min_snr_filter(self):
        proc = SpotProcessor(mycall="MM1E", window_secs=60, history=5,
                             min_snr=10)
        proc.add(spot("W3LPL-#", "G4ABC", 21025, 5, t=1))  # filtered
        proc.add(spot("K1TTT-#", "G4ABC", 21025, 15, t=2))
        s = proc.roll(now=60)
        self.assertEqual(s.total_spots, 1)

    def test_non_contest_band_dropped(self):
        # WARC / off-band spots (band "?") are noise for a contest tool.
        proc = SpotProcessor(mycall="MM1E", window_secs=60, history=5)
        proc.add(spot("W3LPL-#", "G4ABC", 10136, 15, t=1))  # 30m -> "?"
        proc.add(spot("K1TTT-#", "G4ABC", 18100, 15, t=2))  # 17m -> "?"
        proc.add(spot("N4ZR-#", "MM1E", 5357, 15, t=3))     # 60m -> "?"
        proc.add(spot("W3LPL-#", "G4ABC", 21025, 15, t=4))  # 15m -> kept
        self.assertEqual(proc.pending(), 1)
        s = proc.roll(now=60)
        self.assertEqual(s.total_spots, 1)
        self.assertEqual(s.active_bands(), ["15m"])
        self.assertFalse(s.mm_spotted)  # the 60m MM1E spot was dropped


if __name__ == "__main__":
    unittest.main()
