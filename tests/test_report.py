"""Tests for the plain-text report (``--no-tui``).

The text report and the curses TUI must present the same information model so
the two front-ends never drift apart (issue #24). These tests pin the report's
RECOMMENDATION and YOUR STATION sections to the *shared* column definitions in
``rbn_tracker.tables`` and assert the layout renders as an aligned table.
"""

import unittest

from rbn_tracker.processing import SpotProcessor
from rbn_tracker.report import RenderConfig, format_report
from rbn_tracker.spots import parse_spot
from rbn_tracker.tables import REC_COLS, STATION_COLS


def spot(sp, dx, freq, snr, t, wpm=28):
    return parse_spot(f"DX de {sp}: {freq} {dx} CW {snr} dB {wpm} wpm CQ 1200Z",
                      recv_time=t)


def _proc_with_data():
    """NA skimmers hearing a UK station (DX reach) and MM1E (getting out), so
    both the recommendation and your-station tables are populated."""
    proc = SpotProcessor("MM1E", window_secs=60, history=5)
    for i, sp in enumerate(["W3LPL-#", "K1TTT-#", "N4ZR-#"]):
        proc.add(spot(sp, "G4ABC", 21025, 15, t=10 + i))
        proc.add(spot(sp, "MM1E", 21024, 18, t=20 + i))
    proc.commit(60)  # one window of history for trends
    return proc


def _report(use_unicode=True):
    proc = _proc_with_data()
    cfg = RenderConfig(mycall="MM1E", use_unicode=use_unicode, window_secs=60)
    return format_report(proc.snapshot(60), list(proc.history), cfg)


def _header_line(text, *needles):
    return next(l for l in text.splitlines()
               if all(n in l for n in needles))


class TestTextReport(unittest.TestCase):
    def test_sections_present(self):
        text = _report()
        self.assertIn("BAND RECOMMENDATION", text)
        self.assertIn("YOUR STATION", text)

    def test_recommendation_has_tui_column_headings(self):
        text = _report()
        header = _header_line(text, "Target", "Band")
        # Same fields/labels as the TUI recommendation table.
        for col in ("Target", "Band", "Reach", "Trend", "Spots", "Med dB",
                    "Coverage"):
            self.assertIn(col, header)

    def test_station_has_tui_column_headings(self):
        text = _report()
        header = _header_line(text, "Spotters", "Best dB")
        for col in ("Band", "Target", "Spotters", "Trend", "Best dB", "Med dB",
                    "Speed"):
            self.assertIn(col, header)

    def test_headline_fields_are_labelled(self):
        text = _report()
        for label in ("Top DX band:", "Best reach:", "Reach:", "Trend:"):
            self.assertIn(label, text)

    def test_column_values_align_under_headers(self):
        # The data row right after the recommendation header puts its band
        # under the 'Band' column heading (aligned, fixed-width table).
        lines = _report().splitlines()
        hi = next(i for i, l in enumerate(lines)
                  if "Target" in l and "Band" in l)
        header, first_row = lines[hi], lines[hi + 1]
        self.assertEqual(header.index("Band"), first_row.index("15m"))

    def test_field_definitions_are_shared_not_duplicated(self):
        # The report headers come straight from the shared column specs, so the
        # two front-ends can't define different fields/orders.
        text = _report()
        rec_header = _header_line(text, "Target", "Coverage")
        sta_header = _header_line(text, "Spotters", "Speed")
        for _k, h, _a, _p in REC_COLS:
            self.assertIn(h, rec_header)
        for _k, h, _a, _p in STATION_COLS:
            self.assertIn(h, sta_header)

    def test_ascii_mode_is_pure_ascii(self):
        _report(use_unicode=False).encode("ascii")  # must not raise

    def test_not_spotted_message(self):
        proc = SpotProcessor("MM1E", window_secs=60, history=5)
        for i, sp in enumerate(["W3LPL-#", "K1TTT-#"]):
            proc.add(spot(sp, "G4ABC", 21025, 15, t=10 + i))  # no MM1E spots
        proc.commit(60)
        cfg = RenderConfig(mycall="MM1E", use_unicode=True, window_secs=60)
        text = format_report(proc.snapshot(60), list(proc.history), cfg)
        self.assertIn("not spotted", text)


if __name__ == "__main__":
    unittest.main()
