"""Optional CSV logging of per-window, per-cell statistics."""

from __future__ import annotations

import csv
import os
import time

from .analysis import band_horizon_trends, mm_horizon_trends
from .continents import CONTINENTS
from .processing import WindowSummary

CSV_HEADER = [
    "utc_time", "window_secs", "section", "band", "continent",
    "spots", "distinct_uk", "distinct_spotters", "median_snr",
    "reach_pct", "active_uk", "coverage",
    "trend_now", "trend_10min", "trend_30min", "trend_60min",
]


class CsvWriter:
    """Appends one block of rows per window. Flushes after every window."""

    def __init__(self, path: str) -> None:
        self.path = path
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        if new_file:
            self._writer.writerow(CSV_HEADER)
            self._fh.flush()

    def write_window(self, summary: WindowSummary,
                     history: list[WindowSummary]) -> None:
        utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(summary.end_time))
        win = int(round(summary.end_time - summary.start_time))

        for band in summary.active_bands():
            trends = [t for _label, t in band_horizon_trends(history, band, win)]
            active = summary.band_active_uk(band)
            for cont in CONTINENTS:
                cell = summary.cell(band, cont)
                if not cell or cell.count == 0:
                    continue
                med = "" if cell.median_snr is None else f"{cell.median_snr:.0f}"
                reach = f"{100*cell.distinct_uk/active:.0f}" if active else ""
                self._writer.writerow([
                    utc, win, "cohort", band, cont,
                    cell.count, cell.distinct_uk, cell.distinct_spotters,
                    med, reach, active, summary.skimmer_count(cont), *trends,
                ])

        # MM1E rows
        for band in summary.mm_bands():
            trends = [t for _label, t in mm_horizon_trends(history, band, win)]
            for cont in CONTINENTS:
                obs = summary.mm.get((band, cont))
                if not obs:
                    continue
                med = "" if obs.median_snr is None else f"{obs.median_snr:.0f}"
                self._writer.writerow([
                    utc, win, "mm", band, cont,
                    len(obs.snrs), 1, obs.distinct_spotters, med,
                    "", "", summary.skimmer_count(cont), *trends,
                ])
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
