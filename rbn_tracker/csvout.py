"""Optional CSV logging of per-window, per-cell statistics."""

from __future__ import annotations

import csv
import os
import time

from .continents import CONTINENTS
from .processing import (
    WindowSummary,
    band_spotter_series,
    classify_trend,
    mm_band_series,
)

CSV_HEADER = [
    "utc_time", "window_secs", "section", "band", "continent",
    "spots", "distinct_uk", "distinct_spotters", "median_snr", "trend",
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
            band_trend = classify_trend(band_spotter_series(history, band))
            for cont in CONTINENTS:
                cell = summary.cell(band, cont)
                if not cell or cell.count == 0:
                    continue
                med = "" if cell.median_snr is None else f"{cell.median_snr:.0f}"
                self._writer.writerow([
                    utc, win, "cohort", band, cont,
                    cell.count, cell.distinct_uk, cell.distinct_spotters,
                    med, band_trend,
                ])

        # MM1E rows
        for band in summary.mm_bands():
            mm_trend = classify_trend(mm_band_series(history, band))
            for cont in CONTINENTS:
                obs = summary.mm.get((band, cont))
                if not obs:
                    continue
                med = "" if obs.median_snr is None else f"{obs.median_snr:.0f}"
                self._writer.writerow([
                    utc, win, "mm", band, cont,
                    len(obs.snrs), 1, obs.distinct_spotters, med, mm_trend,
                ])
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
