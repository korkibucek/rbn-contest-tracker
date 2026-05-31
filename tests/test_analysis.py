"""Tests for the averaging-window aggregation used by matrix/rec/your-station."""

import unittest

from rbn_tracker import analysis as A
from rbn_tracker.analysis import (
    activity_confidence,
    aggregate_windows,
    coverage_factor,
    mm_current_band,
    per_window_reach,
    score_bands,
    smoothed_reach,
)
from rbn_tracker.processing import (
    COVERAGE_BOOST_CAP,
    SpotProcessor,
    WindowSummary,
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


def _cell(uk, skimmers, snrs, count=None):
    """Build a CellStats with explicit UK stations, skimmers and SNRs."""
    from rbn_tracker.processing import CellStats
    c = CellStats()
    c.uk_stations = set(uk)
    c.spotters = set(skimmers)
    c.snrs = list(snrs)
    c.count = count if count is not None else len(snrs)
    return c


def _window(spec, t_end):
    """One WindowSummary from {(band, cont): (uk, skimmers, snrs, count)}."""
    w = WindowSummary(start_time=t_end - 60, end_time=t_end, mycall="MM1E")
    for key, args in spec.items():
        w.cells[key] = _cell(*args)
    for cont in {c for (_b, c) in spec}:
        sk = set()
        for (b, cc), cell in w.cells.items():
            if cc == cont:
                sk |= cell.spotters
        w.skimmers[cont] = sk
    return w


def _qsy_history(spec, n, t0=10000.0):
    """A history of ``n`` identical windows from one spec (steady opening)."""
    return [_window(spec, t0 + (i + 1) * 60) for i in range(n)]


def _g(n):
    return {"G%d" % i for i in range(n)}


def _sk(prefix, n):
    return {"%s%d" % (prefix, i) for i in range(n)}


# A typical good 15m->NA run the operator is sitting on: full reach, well
# corroborated. Most tests put the operator here and offer a tempting 40m/20m.
_STRONG_15M = ("15m", "NA", (_g(10), _sk("W", 6), [12] * 6, 40))


class QsyEvidenceTest(unittest.TestCase):
    """The QSY engine must gate on evidence quality, not reach % alone."""

    AVG = 5

    def _advice(self, spec, current, n=6, hour=12):
        hist = _qsy_history(spec, n)
        return A.qsy_advice(hist[-1], hist, current, self.AVG, utc_hour=hour)

    def _spec(self, *cells):
        return {(b, c): args for (b, c, args) in cells}

    def test_tiny_denominator_does_not_trigger_qsy(self):
        # The reported bug: 40m->NA "87%" but from 2 stations / 1 skimmer at
        # midday, while running a strong 15m. Must NOT advise a move.
        spec = self._spec(_STRONG_15M,
                          ("40m", "NA", ({"G1", "G2"}, {"W9"}, [20, 21], 2)))
        adv = self._advice(spec, "15m")
        self.assertEqual(adv.tier, A.QSY_NONE)
        self.assertFalse(adv.candidate.meets_minimums)

    def test_weak_signal_only_evidence_is_rejected(self):
        # Plenty of spots and skimmers but every spot near the noise floor.
        spec = self._spec(_STRONG_15M,
                          ("20m", "NA", (_g(8), _sk("K", 6), [-10] * 6, 30)))
        adv = self._advice(spec, "15m")
        self.assertEqual(adv.tier, A.QSY_NONE)
        self.assertFalse(adv.candidate.meets_minimums)
        self.assertLess(adv.candidate.confidence, 0.2)

    def test_low_skimmer_diversity_cannot_qsy_even_with_margin(self):
        # One skimmer hearing strong signals is not corroboration: even with a
        # large reach margin over a weak current band, the hard gate blocks QSY.
        spec = self._spec(
            ("15m", "NA", ({"G1"}, _sk("W", 6), [8] * 6, 30)),      # weak into NA
            ("15m", "EU", (_g(10), {"D1"}, [20] * 5, 50)),          # busy elsewhere
            ("20m", "NA", (_g(10), {"K1"}, [20] * 9, 30)),          # 1 skimmer
        )
        adv = self._advice(spec, "15m", hour=0)
        self.assertNotEqual(adv.tier, A.QSY_MOVE)
        self.assertFalse(adv.candidate.meets_minimums)

    def test_brief_opening_does_not_trigger_qsy(self):
        # Strong-looking but only one window old: not yet trustworthy.
        spec = self._spec(_STRONG_15M,
                          ("20m", "NA", (_g(9), _sk("K", 8), [15] * 9, 30)))
        adv = self._advice(spec, "15m", n=1)
        self.assertEqual(adv.tier, A.QSY_NONE)
        self.assertFalse(adv.candidate.meets_minimums)

    def test_valid_high_confidence_qsy_fires(self):
        # 20m: 10 active, 40 spots, 8 skimmers, solid SNR, persisted; the
        # current 15m only reaches NA weakly. Clear, well-evidenced move.
        spec = self._spec(
            ("15m", "NA", ({"G1", "G2", "G3"}, _sk("W", 6), [8] * 6, 30)),
            ("15m", "EU", (_g(10), {"D1"}, [20] * 5, 50)),  # 15m busy, low NA reach
            ("20m", "NA", (_g(10), _sk("K", 8), [15] * 9, 40)),
        )
        adv = self._advice(spec, "15m", hour=0)
        self.assertEqual(adv.tier, A.QSY_MOVE)
        self.assertEqual(adv.candidate.band, "20m")
        self.assertTrue(adv.candidate.meets_minimums)
        self.assertIn("QSY", adv.message)
        self.assertGreaterEqual(adv.candidate.confidence, 0.6)

    def test_conservative_when_current_band_already_good(self):
        # Candidate is well-evidenced but only marginally better than an already
        # strong current run -> withhold the move.
        spec = self._spec(
            ("15m", "NA", (_g(10), _sk("W", 6), [12] * 6, 40)),   # ~full reach
            ("20m", "NA", (_g(9), _sk("K", 8), [15] * 9, 40)),    # also ~full
        )
        adv = self._advice(spec, "15m", hour=0)
        self.assertEqual(adv.tier, A.QSY_NONE)

    def test_watch_tier_for_building_evidence(self):
        # Medium confidence, a real margin, and a rising trend -> a quiet WATCH
        # note rather than a QSY alert or silence.
        rising = [
            _window({("15m", "NA"): (_g(8), _sk("W", 6), [10] * 6, 30),
                     ("20m", "NA"): (_g(6), _sk("K", n), [10] * n, n)},
                    10000 + (i + 1) * 60)
            for i, n in enumerate([1, 2, 3, 4])  # 20m skimmers climbing
        ]
        adv = A.qsy_advice(rising[-1], rising, "15m", self.AVG, utc_hour=0)
        self.assertIn(adv.tier, (A.QSY_WATCH, A.QSY_NONE))
        if adv.tier == A.QSY_WATCH:
            self.assertIn("Watch", adv.message)

    def test_daytime_prior_lowers_low_band_confidence(self):
        # Identical 40m->NA evidence should score lower at solar noon than at
        # night (D-layer absorption prior) -- a cautious scaling, not a block.
        spec = {("40m", "NA"): (_g(9), _sk("K", 8), [14] * 9, 30)}
        hist = _qsy_history(spec, 6)
        night = A.band_evidence(hist[-1], hist, "40m", "NA", self.AVG,
                                utc_hour=0).confidence
        noon = A.band_evidence(hist[-1], hist, "40m", "NA", self.AVG,
                               utc_hour=12).confidence
        self.assertGreater(night, noon)

    def test_daytime_prior_does_not_touch_high_bands(self):
        spec = {("15m", "NA"): (_g(9), _sk("K", 8), [14] * 9, 30)}
        hist = _qsy_history(spec, 6)
        night = A.band_evidence(hist[-1], hist, "15m", "NA", self.AVG,
                                utc_hour=0).confidence
        noon = A.band_evidence(hist[-1], hist, "15m", "NA", self.AVG,
                               utc_hour=12).confidence
        self.assertEqual(night, noon)

    def test_no_advice_when_not_single_band_run(self):
        spec = self._spec(_STRONG_15M,
                          ("20m", "NA", (_g(10), _sk("K", 8), [15] * 9, 40)))
        hist = _qsy_history(spec, 6)
        adv = A.qsy_advice(hist[-1], hist, None, self.AVG, utc_hour=0)
        self.assertEqual(adv.tier, A.QSY_NONE)

    def test_evidence_exposes_reason_fields(self):
        spec = {("20m", "NA"): (_g(8), _sk("K", 6), [12] * 6, 30)}
        hist = _qsy_history(spec, 6)
        ev = A.band_evidence(hist[-1], hist, "20m", "NA", self.AVG, utc_hour=0)
        self.assertTrue(ev.reasons)
        self.assertEqual(ev.spots, 30)
        self.assertEqual(ev.skimmers, 6)
        self.assertEqual(ev.active_uk, 8)


if __name__ == "__main__":
    unittest.main()
