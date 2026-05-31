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

    def test_panels_and_alignment(self):
        from rbn_tracker.tui import build_footer
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=True, window_secs=60)
        width = 84
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60), None, width=width)
        text = flatten_frame(frame)
        # bordered panels present
        self.assertIn("┌", text)
        self.assertIn("└", text)
        self.assertIn("│", text)
        # every framed line (not the header bar / blank spacers) is exactly the
        # requested width -> borders line up.
        for line in frame:
            s = "".join(t for t, _ in line)
            if s.startswith(" RBN") or not s.strip():
                continue
            self.assertEqual(len(s), width, f"misaligned: {s!r}")
        footer = "".join(t for t, _ in build_footer(cfg, TuiState(now=60), True))
        self.assertIn("[q]", footer)
        self.assertIn("[p]", footer)

    def test_ascii_panels_are_pure_ascii(self):
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60), None, width=80)
        text = flatten_frame(frame)
        text.encode("ascii")  # must not raise
        self.assertIn("+", text)  # ascii box corners
        self.assertIn("|", text)  # ascii vertical border


class TestDisplayWidth(unittest.TestCase):
    """Ambiguous-width handling: the box must line up even in terminals that
    render box-drawing/arrow/sparkline glyphs as two columns."""

    def tearDown(self):
        from rbn_tracker import tui
        tui.set_ambiguous_width(False)  # don't leak state into other tests

    def test_char_width_modes(self):
        from rbn_tracker import tui
        tui.set_ambiguous_width(False)
        self.assertEqual(tui.char_width("─"), 1)   # ambiguous -> 1 normally
        self.assertEqual(tui.char_width("A"), 1)
        self.assertEqual(tui.char_width("世"), 2)  # genuinely wide always
        self.assertEqual(tui.char_width("́"), 0)  # combining mark
        tui.set_ambiguous_width(True)
        self.assertEqual(tui.char_width("─"), 2)   # ambiguous -> 2 when wide
        self.assertEqual(tui.char_width("→"), 2)
        self.assertEqual(tui.char_width("A"), 1)   # ascii unaffected
        self.assertEqual(tui.char_width("世"), 2)

    def test_panels_aligned_in_wide_ambiguous_mode(self):
        from rbn_tracker import tui
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=True, window_secs=60)
        for width in (84, 83, 60):
            tui.set_ambiguous_width(True)
            frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                                TuiState(now=60), None, width=width)
            for line in frame:
                s = "".join(t for t, _ in line)
                if s.startswith(" RBN") or not s.strip():
                    continue
                # measured with the SAME width function the renderer uses
                self.assertEqual(tui.text_width(s), width,
                                 f"misaligned (w={width}): {s!r}")

    def test_detect_respects_env_override(self):
        import os
        from unittest import mock
        from rbn_tracker import tui
        with mock.patch.dict(os.environ, {"RBN_AMBIGUOUS_WIDTH": "wide"}):
            self.assertTrue(tui._detect_ambiguous_wide(None))
        with mock.patch.dict(os.environ, {"RBN_AMBIGUOUS_WIDTH": "narrow"}):
            self.assertFalse(tui._detect_ambiguous_wide(None))

    def test_narrow_width_stays_aligned(self):
        proc = _proc_with_data()
        cfg = RenderConfig(mycall="MM1E", use_unicode=True, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60), None, width=46)
        widths = {len("".join(t for t, _ in line)) for line in frame
                  if "".join(t for t, _ in line).strip()
                  and not "".join(t for t, _ in line).startswith(" RBN")}
        self.assertEqual(widths, {46})

    def test_ascii_mode_empty_state_is_pure_ascii(self):
        # The "no DX activity" / "not spotted" branches must also stay ASCII.
        proc = SpotProcessor("MM1E", 60, 5)
        proc.commit(60)  # an entirely empty window
        cfg = RenderConfig(mycall="MM1E", use_unicode=False, window_secs=60)
        frame = build_frame(proc.snapshot(60), list(proc.history), cfg,
                            TuiState(now=60))
        flatten_frame(frame).encode("ascii")  # must not raise


def _rec_panel_lines(frame):
    """The plain-text lines of the RECOMMENDATION panel (incl. its borders)."""
    lines = ["".join(t for t, _ in line) for line in frame]
    start = next(i for i, s in enumerate(lines) if "RECOMMENDATION" in s)
    end = next(i for i in range(start + 1, len(lines)) if lines[i][:1] in "└+")
    return lines[start:end + 1]


class TestRecommendationPanel(unittest.TestCase):
    """The RECOMMENDATION panel: labelled headline + a fixed-width table."""

    def _frame(self, width, uc=True):
        proc = _proc_with_data()  # NA skimmers hear UK calls -> DX reach into NA
        cfg = RenderConfig(mycall="MM1E", use_unicode=uc, window_secs=60)
        return build_frame(proc.snapshot(60), list(proc.history), cfg,
                           TuiState(now=60), None, width=width)

    def test_headline_fields_are_labelled(self):
        body = "\n".join(_rec_panel_lines(self._frame(84)))
        for label in ("Top DX band:", "Best reach:", "Reach:", "Trend:"):
            self.assertIn(label, body)

    def test_table_has_column_headings(self):
        lines = _rec_panel_lines(self._frame(84))
        header = next(l for l in lines if "Target" in l and "Band" in l)
        for col in ("Target", "Band", "Reach", "Trend", "Spots", "Med dB",
                    "Coverage"):
            self.assertIn(col, header)

    def test_table_columns_align_with_header(self):
        # Each value sits at the same start column as its heading: the data row
        # right after the header puts its band under 'Band'.
        lines = _rec_panel_lines(self._frame(84))
        hi = next(i for i, l in enumerate(lines) if "Target" in l and "Band" in l)
        header, first_row = lines[hi], lines[hi + 1]
        self.assertEqual(header.index("Band"), first_row.index("15m"))

    def test_narrow_terminal_drops_low_priority_columns(self):
        # The wide layout shows Coverage; a narrow one sheds it but keeps the
        # essential Target/Band/Reach/Trend columns.
        wide = next(l for l in _rec_panel_lines(self._frame(84)) if "Target" in l)
        self.assertIn("Coverage", wide)
        narrow = next(l for l in _rec_panel_lines(self._frame(50)) if "Target" in l)
        self.assertNotIn("Coverage", narrow)
        for col in ("Target", "Band", "Reach", "Trend"):
            self.assertIn(col, narrow)

    def test_closed_continents_summarised(self):
        # _proc_with_data only opens NA, so the rest are reported as closed.
        body = "\n".join(_rec_panel_lines(self._frame(84)))
        self.assertIn("closed", body)

    def test_ascii_panel_is_pure_ascii(self):
        body = "\n".join(_rec_panel_lines(self._frame(84, uc=False)))
        body.encode("ascii")  # must not raise


if __name__ == "__main__":
    unittest.main()
