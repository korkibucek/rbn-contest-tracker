"""Tests for run / band-change detection and contest categories."""

import unittest

from rbn_tracker.processing import SpotProcessor
from rbn_tracker.runstate import (
    compute_run_status,
    idle_tx_suggestion,
    normalize_category,
)
from rbn_tracker.spots import parse_spot


def spot(sp, dx, freq, snr, t):
    return parse_spot(f"DX de {sp}: {freq} {dx} CW {snr} dB 28 wpm CQ 1200Z",
                      recv_time=t)


def _run(mm_bands_by_window, cohort=None):
    """Build a processor: mm_bands_by_window[i] = list of bands MM ran in win i."""
    proc = SpotProcessor("MM1E", window_secs=60, history=60)
    t = 0
    spotters = ["W3LPL-#", "K1TTT-#", "N4ZR-#"]
    freqs = {"40m": 7032, "20m": 14032, "15m": 21024}
    for bands in mm_bands_by_window:
        for b in bands:
            for sp in spotters[:2]:
                proc.add(spot(sp, "MM1E", freqs[b], 12, t + 5))
        for b, conts in (cohort or {}).items():
            for sp in spotters:
                proc.add(spot(sp, "G4ABC", freqs[b], 12, t + 6))
        proc.commit(t + 60)
        proc.prune(t + 60)
        t += 60
    return proc, t


class TestCategory(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_category("single"), "single")
        self.assertEqual(normalize_category("SO"), "single")
        self.assertEqual(normalize_category("multi-two"), "m2")
        self.assertEqual(normalize_category("M2"), "m2")
        self.assertEqual(normalize_category("multi-multi"), "mm")
        self.assertEqual(normalize_category("mm"), "mm")

    def test_normalize_bad(self):
        with self.assertRaises(ValueError):
            normalize_category("nonsense")


class TestRunStatus(unittest.TestCase):
    def test_running_now(self):
        proc, t = _run([["40m"], ["40m"], ["40m"]])
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "single")
        self.assertEqual(rs.running_bands, ["40m"])
        self.assertEqual(rs.qsy, [])
        self.assertEqual(rs.sp_or_off, [])

    def test_run_frequency_reported(self):
        proc, t = _run([["40m"], ["40m"], ["40m"]])
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "single")
        # _run() spots MM1E on the 40m test frequency 7032 kHz.
        self.assertIn("40m", rs.frequencies)
        self.assertAlmostEqual(rs.frequencies["40m"], 7032.0, places=1)

    def test_qsy_detected(self):
        proc, t = _run([["40m"], ["40m"], ["40m"], ["15m"], ["15m"]])
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "single")
        self.assertEqual(rs.running_bands, ["15m"])
        self.assertIn(("40m", "15m"), rs.qsy)
        self.assertEqual(rs.sp_or_off, [])  # explained by QSY

    def test_sp_or_off_detected(self):
        # Ran 40m, then three silent windows (no MM spots anywhere).
        proc, t = _run([["40m"], ["40m"], [], [], []])
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "single")
        self.assertEqual(rs.running_bands, [])
        self.assertTrue(any(b == "40m" for b, _m in rs.sp_or_off))

    def test_multi_two_idle_suggestion(self):
        # Running only 40m; cohort shows 15m open into DX.
        proc, t = _run([["40m"], ["40m"], ["40m"]], cohort={"15m": ["NA"]})
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "m2")
        self.assertEqual(rs.running_bands, ["40m"])
        self.assertEqual(rs.spare_tx, 1)
        msg = idle_tx_suggestion(rs, ["15m", "40m"])
        self.assertIsNotNone(msg)
        self.assertIn("15m", msg)

    def test_single_no_idle_suggestion(self):
        proc, t = _run([["40m"], ["40m"], ["40m"]])
        rs = compute_run_status(proc.snapshot(t), list(proc.history), 60, "single")
        self.assertIsNone(idle_tx_suggestion(rs, ["15m", "40m"]))


if __name__ == "__main__":
    unittest.main()
