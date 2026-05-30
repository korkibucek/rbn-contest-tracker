"""Windowing, per-cell aggregation, and cross-window trend tracking.

All tunable thresholds live at the top of this module so they are easy to find
and adjust.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from .bands import UNKNOWN_BAND, band_sort_key
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

# Trend horizons (seconds) shown alongside the current interval. A trend over a
# horizon compares the recent half of that window of history against the older
# half. Tune the set here.
# Labels use "min" (not "m") so they don't read as metre bands (40m vs 10min).
TREND_HORIZONS = [("10min", 600), ("30min", 1800), ("60min", 3600)]
MAX_HORIZON_SECS = max(secs for _label, secs in TREND_HORIZONS)

# --- Reach / activity-normalisation thresholds (tune here) ----------------
# We measure *reach fraction* -- of the UK stations active (heard anywhere) on a
# band, what fraction are reaching a given continent -- so a band reading isn't
# dominated by how busy the band happens to be with UK stations.
REACH_CONF_K = 5      # active-UK half-saturation for confidence: conf=n/(n+K)
REACH_EWMA_ALPHA = 0.4  # exponential smoothing of per-window reach (0..1)
# Coverage adjustment: continents with fewer than REF active skimmers get their
# reach signal boosted (a detection where few are listening means more), capped.
COVERAGE_REF_SKIMMERS = 50
COVERAGE_BOOST_CAP = 3.0

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
    freqs: list[float] = field(default_factory=list)

    def add(self, spot: Spot) -> None:
        self.spotters.add(spot.spotter)
        self.snrs.append(spot.snr_db)
        self.freqs.append(spot.freq_khz)
        if spot.speed_wpm is not None:
            self.speeds.append(spot.speed_wpm)

    @property
    def distinct_spotters(self) -> int:
        return len(self.spotters)

    @property
    def frequency(self) -> float | None:
        """Representative run frequency (kHz) -- median of skimmer reports."""
        return statistics.median(self.freqs) if self.freqs else None

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
    # active-skimmer census per continent, from ALL spots (UK or not) -- used to
    # gauge how much listening coverage each continent has.
    skimmers: dict[str, set[str]] = field(default_factory=dict)

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

    def band_active_uk(self, band: str) -> int:
        """Distinct UK stations heard *anywhere* on this band (reach denominator)."""
        s: set[str] = set()
        for (b, _c), cell in self.cells.items():
            if b == band:
                s |= cell.uk_stations
        return len(s)

    def skimmer_count(self, cont: str) -> int:
        return len(self.skimmers.get(cont, ()))

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

    def mm_band_freq(self, band: str) -> float | None:
        """Representative frequency (kHz) the tracked station ran on this band."""
        freqs: list[float] = []
        for (b, _c), obs in self.mm.items():
            if b == band:
                freqs.extend(obs.freqs)
        return statistics.median(freqs) if freqs else None

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
        # Retain enough completed windows to cover the longest trend horizon
        # (an hour) regardless of the requested short-trend depth.
        retain = max(history, windows_for_secs(MAX_HORIZON_SECS, window_secs)) + 1
        self.history: deque[WindowSummary] = deque(maxlen=max(1, retain))

    def add(self, spot: Spot) -> None:
        # Ignore anything off the HF contest bands (WARC/60m/6m/out-of-band):
        # band_for() returns "?" for those and they're noise for this tool.
        if spot.band == UNKNOWN_BAND:
            return
        if self.min_snr is not None and spot.snr_db < self.min_snr:
            return
        self._buffer.append(spot)

    def pending(self) -> int:
        return len(self._buffer)

    def _build_summary(self, start: float, now: float,
                       spots: list[Spot]) -> WindowSummary:
        summary = WindowSummary(start_time=start, end_time=now, mycall=self.mycall)
        for s in spots:
            if not (start < s.recv_time <= now):
                continue
            summary.total_spots += 1
            # Skimmer census: every spot means this skimmer is listening in its
            # continent, regardless of who it heard.
            summary.skimmers.setdefault(s.spotter_continent, set()).add(s.spotter)
            if s.is_uk:
                summary.total_uk_spots += 1
                key = (s.band, s.spotter_continent)
                summary.cells.setdefault(key, CellStats()).add(s)
            if same_station(s.spotted, self.mycall):
                mkey = (s.band, s.spotter_continent)
                summary.mm.setdefault(mkey, MmObservation()).add(s)
        return summary

    def roll(self, now: float) -> WindowSummary:
        """Build a discrete window summary, append to history, advance the buffer.

        The window is keyed off *receive time*, not the Zulu field. Spots at or
        before ``now`` are consumed; future spots (possible during replay) are
        kept. Used by the classic line-report path.
        """
        start = now - self.window_secs
        summary = self._build_summary(start, now, self._buffer)
        self._buffer = [s for s in self._buffer if s.recv_time > now]
        self.history.append(summary)
        return summary

    def prune(self, now: float) -> None:
        """Drop spots older than the current rolling window (bounds the buffer)."""
        cutoff = now - self.window_secs
        self._buffer = [s for s in self._buffer if s.recv_time > cutoff]

    def snapshot(self, now: float) -> WindowSummary:
        """Build a summary of the *current rolling window* without mutating state.

        Used by the live TUI to redraw continuously between window commits.
        """
        return self._build_summary(now - self.window_secs, now, self._buffer)

    def commit(self, now: float) -> WindowSummary:
        """Snapshot the current rolling window into history (for trends/CSV).

        Does not clear the buffer; :meth:`prune` bounds it by age so successive
        commits one window apart are effectively non-overlapping.
        """
        summary = self.snapshot(now)
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


def _mean(xs: list[int]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def classify_horizon(series: list[int], n_windows: int) -> str:
    """Classify the trajectory over the last ``n_windows`` windows.

    Unlike :func:`classify_trend` (which keys off the immediate window-to-window
    step), this compares the *recent half* of the horizon against the *older
    half* -- so it captures the longer-run direction over 10/30/60 minutes.
    """
    if not series:
        return STEADY
    seg = series[-n_windows:] if n_windows < len(series) else list(series)
    if len(seg) < 2:
        cur = seg[-1] if seg else 0
        return NEW if cur >= MEANINGFUL_SPOTTERS else STEADY
    mid = len(seg) // 2
    older = seg[:mid] if mid > 0 else seg[:1]
    newer = seg[mid:]
    om, nm = _mean(older), _mean(newer)

    if om <= NEAR_ZERO_SPOTTERS and nm >= MEANINGFUL_SPOTTERS:
        return NEW
    if om >= MEANINGFUL_SPOTTERS and nm <= GONE_FLOOR:
        return GONE
    if om <= 0:
        return RISING if nm >= MEANINGFUL_SPOTTERS else STEADY
    ratio = nm / om
    if ratio >= RISE_FACTOR:
        return RISING
    if ratio <= FADE_FACTOR:
        return FADING
    return STEADY


def windows_for_secs(secs: int, window_secs: int) -> int:
    """Number of windows spanning ``secs`` seconds (at least 2)."""
    return max(2, round(secs / window_secs)) if window_secs > 0 else 2


def band_spotter_series(history: list[WindowSummary], band: str) -> list[int]:
    """Distinct-spotter count for ``band`` across each window (oldest..newest)."""
    return [w.band_spotters(band) for w in history]


def mm_band_series(history: list[WindowSummary], band: str) -> list[int]:
    return [w.mm_band_spotters(band) for w in history]
