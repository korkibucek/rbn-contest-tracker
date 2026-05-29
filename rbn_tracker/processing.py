"""Windowing, per-cell aggregation, and cross-window trend tracking.

All tunable thresholds live at the top of this module so they are easy to find
and adjust.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .bands import band_sort_key
from .callsign import same_station
from .continents import CONTINENTS
from .spots import Spot

# --- Trend thresholds (tune here) -----------------------------------------
# Trends are computed on the *distinct-spotter* series for a band (less noisy
# than raw spot counts).
RISE_FACTOR = 1.30  # current >= prev * this  -> candidate RISING
FADE_FACTOR = 0.70  # current <= prev * this  -> FADING
RISE_MIN_STREAK = 2  # consecutive increasing windows required for RISING
NEAR_ZERO_SPOTTERS = 1  # <= this counts as effectively no activity
MEANINGFUL_SPOTTERS = 2  # >= this is a real opening (for NEW)
GONE_FLOOR = 1  # now <= this (with prior activity) -> GONE

# Trend labels
RISING, STEADY, FADING, NEW, GONE = "RISING", "STEADY", "FADING", "NEW", "GONE"

# DX continents (everything that isn't EU) -- what a UK contester wants to work.
DX_CONTINENTS = [c for c in CONTINENTS if c != "EU"]


@dataclass
class CellStats:
    """Aggregate stats for one (band x continent) cell."""

    count: int = 0
    uk_stations: set[str] = field(default_factory=set)
    spotters: set[str] = field(default_factory=set)
    snrs: list[int] = field(default_factory=list)

    def add(self, spot: Spot) -> None:
        self.count += 1
        self.uk_stations.add(spot.spotted)
        self.spotters.add(spot.spotter)
        self.snrs.append(spot.snr_db)

    @property
    def distinct_uk(self) -> int:
        return len(self.uk_stations)

    @property
    def distinct_spotters(self) -> int:
        return len(self.spotters)

    @property
    def median_snr(self) -> float | None:
        return statistics.median(self.snrs) if self.snrs else None


@dataclass
class MmObservation:
    """Per (band x continent) view of the tracked 'me' station."""

    spotters: set[str] = field(default_factory=set)
    snrs: list[int] = field(default_factory=list)
    speeds: list[int] = field(default_factory=list)

    def add(self, spot: Spot) -> None:
        self.spotters.add(spot.spotter)
        self.snrs.append(spot.snr_db)
        if spot.speed_wpm is not None:
            self.speeds.append(spot.speed_wpm)

    @property
    def distinct_spotters(self) -> int:
        return len(self.spotters)

    @property
    def best_snr(self) -> int | None:
        return max(self.snrs) if self.snrs else None

    @property
    def median_snr(self) -> float | None:
        return statistics.median(self.snrs) if self.snrs else None

    @property
    def typical_speed(self) -> int | None:
        return round(statistics.median(self.speeds)) if self.speeds else None


@dataclass
class WindowSummary:
    """Aggregated results for one time window."""

    start_time: float
    end_time: float
    mycall: str

    total_spots: int = 0
    total_uk_spots: int = 0
    cells: dict[tuple[str, str], CellStats] = field(default_factory=dict)
    # me-station observations keyed by (band, continent)
    mm: dict[tuple[str, str], MmObservation] = field(default_factory=dict)

    def cell(self, band: str, cont: str) -> CellStats | None:
        return self.cells.get((band, cont))

    def active_bands(self) -> list[str]:
        bands = {b for (b, _c) in self.cells}
        return sorted(bands, key=band_sort_key)

    # --- band-level rollups (across continents) ---
    def band_spotters(self, band: str) -> int:
        s: set[str] = set()
        for (b, _c), cell in self.cells.items():
            if b == band:
                s |= cell.spotters
        return len(s)

    def band_count(self, band: str) -> int:
        return sum(c.count for (b, _c), c in self.cells.items() if b == band)

    # --- me-station rollups ---
    def mm_bands(self) -> list[str]:
        bands = {b for (b, _c) in self.mm}
        return sorted(bands, key=band_sort_key)

    def mm_band_spotters(self, band: str) -> int:
        s: set[str] = set()
        for (b, _c), obs in self.mm.items():
            if b == band:
                s |= obs.spotters
        return len(s)

    @property
    def mm_spotted(self) -> bool:
        return bool(self.mm)


class SpotProcessor:
    """Buffers spots, rolls fixed-length windows, and keeps a window history."""

    def __init__(self, mycall: str, window_secs: int = 60, history: int = 5,
                 min_snr: int | None = None) -> None:
        self.mycall = (mycall or "").strip().upper()
        self.window_secs = window_secs
        self.min_snr = min_snr
        self._buffer: list[Spot] = []
        self.history: deque[WindowSummary] = deque(maxlen=max(1, history))

    def add(self, spot: Spot) -> None:
        if self.min_snr is not None and spot.snr_db < self.min_snr:
            return
        self._buffer.append(spot)

    def pending(self) -> int:
        return len(self._buffer)

    def roll(self, now: float) -> WindowSummary:
        """Build a :class:`WindowSummary` from spots received in the last window.

        The window is keyed off *receive time*, not the Zulu field. Older spots
        are discarded; the summary is appended to history and returned.
        """
        start = now - self.window_secs
        in_window = [s for s in self._buffer if start < s.recv_time <= now]
        # Retain spots that belong to a future window (can happen during
        # replay); drop everything at or before this window's end.
        self._buffer = [s for s in self._buffer if s.recv_time > now]

        summary = WindowSummary(
            start_time=start, end_time=now, mycall=self.mycall
        )
        for s in in_window:
            summary.total_spots += 1
            if s.is_uk:
                summary.total_uk_spots += 1
                key = (s.band, s.spotter_continent)
                summary.cells.setdefault(key, CellStats()).add(s)
            if same_station(s.spotted, self.mycall):
                mkey = (s.band, s.spotter_continent)
                summary.mm.setdefault(mkey, MmObservation()).add(s)

        self.history.append(summary)
        return summary


# --- Trend classification --------------------------------------------------

def _trailing_increasing_steps(series: list[int]) -> int:
    steps = 0
    for i in range(len(series) - 1, 0, -1):
        if series[i] > series[i - 1]:
            steps += 1
        else:
            break
    return steps


def classify_trend(series: list[int]) -> str:
    """Classify a distinct-spotter series (oldest..current) into a trend label.

    The last element is the current window.
    """
    if not series:
        return STEADY
    cur = series[-1]
    prior = series[:-1]
    prev = prior[-1] if prior else 0
    prior_max = max(prior) if prior else 0

    # First time we've seen this band at all.
    if not prior:
        return NEW if cur >= MEANINGFUL_SPOTTERS else STEADY

    # NEW: essentially nothing before, meaningful now.
    if prior_max <= NEAR_ZERO_SPOTTERS and cur >= MEANINGFUL_SPOTTERS:
        return NEW
    # GONE: had real activity, now gone.
    if prior_max >= MEANINGFUL_SPOTTERS and cur <= GONE_FLOOR:
        return GONE

    if prev <= 0:
        return RISING if cur >= MEANINGFUL_SPOTTERS else STEADY

    if cur >= prev * RISE_FACTOR and _trailing_increasing_steps(series) >= min(
        RISE_MIN_STREAK, len(series) - 1
    ):
        return RISING
    if cur <= prev * FADE_FACTOR:
        return FADING
    return STEADY


def band_spotter_series(history: list[WindowSummary], band: str) -> list[int]:
    """Distinct-spotter count for ``band`` across each window (oldest..newest)."""
    return [w.band_spotters(band) for w in history]


def cell_spotter_series(history: list[WindowSummary], band: str,
                        cont: str) -> list[int]:
    out = []
    for w in history:
        cell = w.cell(band, cont)
        out.append(cell.distinct_spotters if cell else 0)
    return out


def mm_band_series(history: list[WindowSummary], band: str) -> list[int]:
    return [w.mm_band_spotters(band) for w in history]
