"""Tests for the opponents / live-scoreboard interface."""

import json
import os
import tempfile
import unittest

from rbn_tracker.opponents import (
    ContestOnlineScoreSource,
    ManualSource,
    Opponent,
    OpponentsManager,
    RunTracker,
    build_leaderboard,
    class_to_category,
    parse_score_records,
)
from rbn_tracker.spots import parse_spot


class TestCategoryMap(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(class_to_category("SO"), "single")
        self.assertEqual(class_to_category("Single-Op HP"), "single")
        self.assertEqual(class_to_category("Multi-Single"), "single")
        self.assertEqual(class_to_category("ONE"), "single")
        self.assertEqual(class_to_category("M/2"), "m2")
        self.assertEqual(class_to_category("MULTI-TWO"), "m2")
        self.assertEqual(class_to_category("TWO"), "m2")
        self.assertEqual(class_to_category("M/M"), "mm")
        self.assertEqual(class_to_category("Multi-Unlimited"), "mm")
        self.assertIsNone(class_to_category(""))


class TestParse(unittest.TestCase):
    def test_tolerant_fields(self):
        data = {"scores": [
            {"call": "GM4DEF", "class": "SO", "qsos": 1500, "mults": 420,
             "score": 1300000},
            {"callsign": "MM1E", "category": "Single-Op", "qso": 1400,
             "mult": 405, "score": "1,180,000"},
        ]}
        opps = parse_score_records(data)
        self.assertEqual(len(opps), 2)
        self.assertEqual(opps[0].call, "GM4DEF")
        self.assertEqual(opps[1].score, 1180000)  # comma-formatted parsed
        self.assertEqual(opps[1].qsos, 1400)
        self.assertEqual(opps[1].category, "single")


class TestLeaderboard(unittest.TestCase):
    def test_window_around_me(self):
        opps = [Opponent(f"C{i}", score=1000 - i * 10) for i in range(20)]
        opps.append(Opponent("MM1E", score=905))  # ranks mid-pack
        lb = build_leaderboard(opps, "MM1E", window=2)
        calls = [o.call for o in lb]
        self.assertIn("MM1E", calls)
        self.assertEqual(len(calls), 5)  # 2 above + me + 2 below

    def test_me_missing_returns_top(self):
        opps = [Opponent(f"C{i}", score=1000 - i) for i in range(10)]
        lb = build_leaderboard(opps, "MM1E", window=2)
        self.assertEqual(len(lb), 5)
        self.assertEqual(lb[0].call, "C0")


class TestManualSource(unittest.TestCase):
    def test_parse_file(self):
        text = ("# comment\nGM4DEF, 1500, 420, 1300000\n"
                "MM1E,1400,405,1180000\nGW9T\n")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            opps = ManualSource(path).fetch()
        finally:
            os.unlink(path)
        self.assertEqual([o.call for o in opps], ["GM4DEF", "MM1E", "GW9T"])
        self.assertEqual(opps[0].score, 1300000)
        self.assertIsNone(opps[2].score)  # call-only line


class TestRunTracker(unittest.TestCase):
    def test_current_run_freq(self):
        tr = RunTracker()
        tr.set_watch(["GM4DEF", "MM1E"])
        sp = parse_spot("DX de W3LPL-#: 21024.0 GM4DEF CW 12 dB 28 wpm CQ 1200Z",
                        recv_time=100.0)
        tr.note(sp.spotted, sp.freq_khz, sp.recv_time)
        info = tr.current("GM4DEF", now=150.0)
        self.assertIsNotNone(info)
        self.assertAlmostEqual(info.freq_khz, 21024.0)
        self.assertEqual(info.band, "15m")
        # stale after the freshness window
        self.assertIsNone(tr.current("GM4DEF", now=100.0 + 10_000))
        # not watched
        self.assertIsNone(tr.current("G4XYZ", now=150.0))


class TestAutoSource(unittest.TestCase):
    def _payload(self):
        return json.dumps({"scores": [
            {"call": "GM4DEF", "class": "SO", "score": 1300000, "qsos": 1500,
             "mults": 420},
            {"call": "MM1E", "class": "SO", "score": 1180000, "qsos": 1400,
             "mults": 405},
            {"call": "DL9X", "class": "M/2", "score": 9999999},  # other category
        ]}).encode()

    def test_filters_by_category(self):
        src = ContestOnlineScoreSource("single", "MM1E", url="http://x",
                                       fetcher=lambda u: self._payload())
        calls = [o.call for o in src.fetch()]
        self.assertIn("GM4DEF", calls)
        self.assertIn("MM1E", calls)
        self.assertNotIn("DL9X", calls)  # M/2 filtered out

    def test_missing_url_raises(self):
        src = ContestOnlineScoreSource("single", "MM1E")  # no url/contest
        with self.assertRaises(Exception):
            src.fetch()


class TestManagerView(unittest.TestCase):
    def test_deltas_and_run(self):
        src = ContestOnlineScoreSource("single", "MM1E", url="http://x",
            fetcher=lambda u: json.dumps({"scores": [
                {"call": "GM4DEF", "class": "SO", "score": 1300000,
                 "qsos": 1500, "mults": 420},
                {"call": "MM1E", "class": "SO", "score": 1180000,
                 "qsos": 1400, "mults": 405},
            ]}).encode())
        mgr = OpponentsManager(src, "MM1E", "Single", window=5, auto=False)
        mgr.refresh(0.0, force=True)
        sp = parse_spot("DX de W3LPL-#: 21024.0 GM4DEF CW 12 dB 28 wpm CQ 1200Z",
                        recv_time=100.0)
        mgr.note_spot(sp)
        view = mgr.view(now=120.0)
        self.assertTrue(view.enabled)
        by_call = {e.call: e for e in view.entries}
        self.assertEqual(by_call["GM4DEF"].d_score, 120000)  # ahead of me
        self.assertEqual(by_call["GM4DEF"].d_qsos, 100)
        self.assertTrue(by_call["MM1E"].is_me)
        self.assertIsNone(by_call["MM1E"].d_score)
        self.assertIsNotNone(by_call["GM4DEF"].run)  # run freq cross-referenced
        self.assertAlmostEqual(by_call["GM4DEF"].run.freq_khz, 21024.0)


if __name__ == "__main__":
    unittest.main()
