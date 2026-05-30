"""Tests for the averaging-window aggregation used by matrix/rec/your-station."""

import unittest

from rbn_tracker.analysis import (
    activity_confidence,
    aggregate_windows,
    coverage_factor,
    mm_current_band,
    per_window_reach,
    recommended_dx_band,
    score_bands,
    smoothed_reach,
)
from rbn_tracker.processing import (
    COVERAGE_BOOST_CAP,
    SpotProcessor,
    windows_for_secs,
)
from rbn_tracker.spots import parse_spot


def spot(sp, dx, freq, snr, t, wpm=28):
    return parse_spot(f"DX de {sp}: {freq} {dx} CW {snr} dB {wpm} wpm CQ 1200Z",
                      recv_time=t)


def _proc_three_windows():
    """15m NA grows over three committed 60s windows; MM heard on 15m."""
    proc = SpotProcessor("MM1E", window_secs=60, history=60)
    # window 1 (MM1E is itself a UK station, so it counts in the cohort too)
    proc.add(spot("W3LPL-#", "G4ABC", 21025, 15, 10))
    proc.add(spot("K1TTT-#", "MM1E", 21025, 18, 11))
    proc.commit(60); proc.prune(60)
    # window 2
    proc.add(spot("W3LPL-#", "M0ABC", 21025, 14, 70))
    proc.add(spot("N4ZR-#", "G4ABC", 21025, 16, 75))
    proc.add(spot("N4ZR-#", "MM1E", 21025, 20, 76))
    proc.commit(120); proc.prune(120)
    # window 3
    proc.add(spot("VE3EID-#", "GW4ZZZ", 21025, 12, 130))
    proc.commit(180); proc.prune(180)
    return proc


class TestAggregation(unittest.TestCase):
    def test_window_totals_and_union(self):
        proc = _proc_three_windows()
        view = aggregate_windows(proc.snapshot(180), list(proc.history),
                                 windows_for_secs(900, 60))
        cell = view.cell("15m", "NA")
        self.assertIsNotNone(cell)
        # spot counts sum across windows; distinct spotters are unioned.
        self.assertEqual(cell.count, 6)  # 3 + 2 + 1 cohort spots on 15m NA
        self.assertEqual(cell.distinct_spotters, 4)  # W3LPL,K1TTT,N4ZR,VE3EID

    def test_smaller_window_sees_less(self):
        proc = _proc_three_windows()
        # 1-window average = only the most recent committed window.
        view = aggregate_windows(proc.snapshot(180), list(proc.history), 1)
        cell = view.cell("15m", "NA")
        self.assertEqual(cell.count, 1)
        self.assertEqual(cell.distinct_spotters, 1)  # just VE3EID

    def test_score_and_mm_over_window(self):
        proc = _proc_three_windows()
        view = aggregate_windows(proc.snapshot(180), list(proc.history),
                                 windows_for_secs(900, 60))
        scored = score_bands(view, list(proc.history), windows_for_secs(900, 60))
        self.assertTrue(scored)
        self.assertEqual(scored[0].band, "15m")  # top DX band
        # MM heard on 15m by two distinct NA spotters over the window.
        self.assertEqual(mm_current_band(view), "15m")
        self.assertEqual(view.mm_band_spotters("15m"), 2)  # K1TTT + N4ZR


class TestReach(unittest.TestCase):
    def _window(self, na_calls, eu_calls, na_skimmers=3, eu_skimmers=80):
        """One window: given UK calls heard on 20m in NA and in EU."""
        proc = SpotProcessor("MM1E", window_secs=60, history=5)
        t = 0
        for i in range(na_skimmers):
            for c in na_calls:
                proc.add(spot(f"K{i}AA-#", c, 14025, 12, t + 1))
        for i in range(eu_skimmers):
            for c in eu_calls:
                proc.add(spot(f"DL{i}X-#", c, 14025, 12, t + 1))
        return proc.roll(60)

    def test_reach_fraction(self):
        # 2 UK stations reach NA; 5 UK stations active on the band (heard in EU).
        w = self._window(na_calls=["G4ABC", "M0XYZ"],
                         eu_calls=["G4ABC", "M0XYZ", "GW4ZZZ", "MI0JKL", "GM4DEF"])
        self.assertEqual(w.band_active_uk("20m"), 5)
        self.assertAlmostEqual(per_window_reach([w], "20m", "NA")[0], 2 / 5)

    def test_smoothed_reach_ewma(self):
        w1 = self._window(["G4ABC"], ["G4ABC", "M0XYZ", "GW4ZZZ", "MI0JKL"])  # 1/4
        w2 = self._window(["G4ABC", "M0XYZ"],
                          ["G4ABC", "M0XYZ", "GW4ZZZ", "MI0JKL"])  # 2/4
        sr = smoothed_reach([w1, w2], "20m", "NA", alpha=0.5)
        # EWMA(0.25 -> 0.5, a=0.5) = 0.375
        self.assertAlmostEqual(sr, 0.375, places=3)

    def test_confidence_grows_with_activity(self):
        small = self._window(["G4ABC"], ["G4ABC", "M0XYZ"])  # n=2
        big_eu = [f"G{i}ABC" for i in range(30)]
        big = self._window(["G0ABC"], big_eu)  # n=30
        self.assertLess(activity_confidence(small, "20m"),
                        activity_confidence(big, "20m"))

    def test_coverage_factor_boosts_sparse(self):
        # NA dense -> no boost; AF with few skimmers -> boosted (capped).
        w = self._window(["G4ABC"], ["G4ABC", "M0XYZ"],
                         na_skimmers=200, eu_skimmers=200)
        self.assertEqual(coverage_factor(w, "NA"), 1.0)
        # Synthesize a sparse AF census.
        w.skimmers["AF"] = {"ZS1A"}
        self.assertGreater(coverage_factor(w, "AF"), 1.0)
        self.assertLessEqual(coverage_factor(w, "AF"), COVERAGE_BOOST_CAP)

    def test_quiet_high_reach_beats_busy_low_reach(self):
        # Band A (15m): quiet but most active UK reach NA. Band B (20m): busy but
        # few reach NA. Reach-based scoring should prefer the opener.
        proc = SpotProcessor("MM1E", window_secs=60, history=20)
        t = 0
        for w in range(5):
            # 15m: 4 active UK (in EU), 3 of them also into NA -> 75% reach
            for c in ["GA1", "GB2", "GC3", "GD4"]:
                proc.add(spot("DL9X-#", c, 21025, 12, t + 1))
            for c in ["GA1", "GB2", "GC3"]:
                for k in range(4):
                    proc.add(spot(f"W{k}AA-#", c, 21025, 12, t + 1))
            # 20m: 40 active UK (in EU), only 2 into NA -> 5% reach
            for i in range(40):
                proc.add(spot("DL8X-#", f"M{i}QQ", 14025, 12, t + 1))
            for c in ["M0QQ", "M1QQ"]:
                for k in range(4):
                    proc.add(spot(f"K{k}BB-#", c, 14025, 12, t + 1))
            proc.commit(t + 60)
            proc.prune(t + 60)
            t += 60
        view = aggregate_windows(proc.snapshot(t), list(proc.history),
                                 windows_for_secs(900, 60))
        scored = score_bands(view, list(proc.history), windows_for_secs(900, 60))
        self.assertEqual(scored[0].band, "15m")  # the opener wins


if __name__ == "__main__":
    unittest.main()
