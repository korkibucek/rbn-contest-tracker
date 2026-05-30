"""Tests for the TUI frame builder (pure layout, no curses)."""

import unittest

from rbn_tracker.processing import SpotProcessor
from rbn_tracker.report import RenderConfig
from rbn_tracker.spots import parse_spot
from rbn_tracker.tui import TuiState, build_frame, flatten_frame


def spot(sp, dx, freq, snr, t, wpm=28):
    return parse_spot(f"DX de {sp}: {freq} {dx} CW {snr} dB {wpm} wpm CQ 1200Z",
                      recv_time=t)


def _proc_with_data():
    proc = SpotProcessor("MM1E", window_secs=60, history=5)
    for i, sp in enumerate(["W3LPL-#", "K1TTT-#", "N4ZR-#"]):
        proc.add(spot(sp, "G4ABC", 21025, 15, t=10 + i))
        proc.add(spot(sp, "MM1E", 21024, 18, t=20 + i))
    proc.commit(60)  # one window of history for trends
    return proc


class TestBuildFrame(unittest.TestCase):
    def test_sections_present(self):
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=True, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(source="live", connected=True, now=60))
        text = flatten_frame(frame)
        self.assertIn("BAND", text)
        self.assertIn("CONTINENT", text)
        self.assertIn("BAND TRENDS", text)
        self.assertIn("RECOMMENDATION", text)
        self.assertIn("YOUR STATION", text)
        self.assertIn("MM1E", text)
        self.assertIn("15m", text)
        # multi-horizon labels (use "min" so they don't read as metre bands)
        for h in ("now", "10min", "30min", "60min"):
            self.assertIn(h, text)

    def test_not_spotted_message(self):
        proc = SpotProcessor("MM1E", 60, 5)
        proc.add(spot("W3LPL-#", "G4ABC", 21025, 15, t=10))
        proc.commit(60)
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60))
        self.assertIn("not spotted", flatten_frame(frame))

    def test_quiet_window_keeps_band_visible(self):
        # A band active earlier must still render (fading) during an empty
        # window, rather than vanishing -- the zero window is tracked, not wiped.
        proc = SpotProcessor("MM1E", window_secs=60, history=5)
        for i, sp in enumerate(["W3LPL-#", "K1TTT-#", "N4ZR-#"]):
            proc.add(spot(sp, "G4ABC", 21025, 15, t=10 + i))
        proc.commit(60)
        proc.prune(60)
        proc.commit(120)  # quiet window: no UK spots at all
        proc.prune(120)
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(120), list(proc.history), cfg,
                            TuiState(now=120))
        text = flatten_frame(frame)
        self.assertIn("15m", text)          # band still shown
        self.assertIn("BAND TRENDS", text)  # trends panel populated
        self.assertNotIn("recent history)", text)  # not the empty-state message

    def test_ascii_mode_is_pure_ascii(self):
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60))
        flatten_frame(frame).encode("ascii")  # must not raise

    def test_opponents_panel(self):
        from rbn_tracker.opponents import Opponent, OpponentsManager
        from rbn_tracker.spots import parse_spot

        class _Src:
            def label(self):
                return "test"

            def fetch(self):
                return [Opponent("GM4DEF", 1500, 420, 1300000),
                        Opponent("MM1E", 1400, 405, 1180000)]

        mgr = OpponentsManager(_Src(), "MM1E", "Single", window=5, auto=False)
        mgr.refresh(0.0, force=True)
        mgr.note_spot(parse_spot(
            "DX de W3LPL-#: 21024.0 GM4DEF CW 12 dB 28 wpm CQ 1200Z",
            recv_time=100.0))
        view = mgr.view(now=120.0)
        proc = _proc_with_data()
        for uc in (True, False):
            cfg = RenderConfig(mycall="MM1E", use_unicode=uc, window_secs=60)
            frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                                TuiState(now=120.0), view)
            text = flatten_frame(frame)
            self.assertIn("OPPONENTS", text)
            self.assertIn("GM4DEF", text)
            self.assertIn("21024.0", text)  # rival run frequency
            if not uc:
                text.encode("ascii")  # must not raise

    def test_ascii_mode_empty_state_is_pure_ascii(self):
        # The "no DX activity" / "not spotted" branches must also stay ASCII.
        proc = SpotProcessor("MM1E", 60, 5)
        proc.commit(60)  # an entirely empty window
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60))
        flatten_frame(frame).encode("ascii")  # must not raise


if __name__ == "__main__":
    unittest.main()
