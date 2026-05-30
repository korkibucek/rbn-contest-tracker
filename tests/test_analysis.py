"""Tests for the averaging-window aggregation used by matrix/rec/your-station."""

import unittest

from rbn_tracker.analysis import (
    aggregate_windows,
    mm_current_band,
    recommended_dx_band,
    score_bands,
)
from rbn_tracker.processing import SpotProcessor, windows_for_secs
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
        self.assertEqual(scored[0][1], "15m")  # top DX band
        # MM heard on 15m by two distinct NA spotters over the window.
        self.assertEqual(mm_current_band(view), "15m")
        self.assertEqual(view.mm_band_spotters("15m"), 2)  # K1TTT + N4ZR


if __name__ == "__main__":
    unittest.main()
