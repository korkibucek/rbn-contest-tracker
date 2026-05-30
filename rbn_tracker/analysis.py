"""Shared recommendation / scoring logic used by both the text report and TUI.

Keeping this in one place means the plain-text report and the full-screen viewer
can never drift apart in how they rank bands or pick the QSY suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bands import band_sort_key
from .processing import (
    COVERAGE_BOOST_CAP,
    COVERAGE_REF_SKIMMERS,
    DX_CONTINENTS,
    FADING,
    GONE,
    NEW,
    REACH_CONF_K,
    REACH_EWMA_ALPHA,
    RISING,
    STEADY,
    TREND_HORIZONS,
    CellStats,
    MmObservation,
    WindowSummary,
    band_spotter_series,
    classify_horizon,
    mm_band_series,
    windows_for_secs,
)

# Trend weighting for the recommendation engine: a band that is opening should
# outrank a higher-count band that is closing.
TREND_WEIGHT = {RISING: 1.6, NEW: 1.4, STEADY: 1.0, FADING: 0.45, GONE: 0.1}

# Default averaging window (seconds) for the recommendation and "your station"
# sections -- smooths out per-window noise. Overridable via --avg-window.
DEFAULT_AVG_WINDOW_SECS = 900  # 15 minutes


def minutes_label(secs: float) -> str:
    """Format a seconds duration as e.g. '15min' / '7.5min'."""
    m = secs / 60.0
    return f"{int(m)}min" if m == int(m) else f"{m:g}min"


def _recent(history: list[WindowSummary], n: int) -> list[WindowSummary]:
    """The last ``n`` committed windows (all of them if fewer exist)."""
    h = list(history)
    if n <= 0 or n >= len(h):
        return h
    return h[-n:]


def display_bands(summary: WindowSummary,
                  history: list[WindowSummary]) -> list[str]:
    """Bands worth showing: active in the current window OR seen in history.

    This keeps a band on screen as it fades through quiet/zero windows (so the
    trend stays visible) instead of vanishing the moment a window has no spots.
    A band drops off only once it has been silent across the entire retained
    history (an hour), at which point it no longer appears in any window's cells.
    """
    bands = set(summary.active_bands())
    for w in history:
        bands.update(b for (b, _c) in w.cells)
    return sorted(bands, key=band_sort_key)


def _horizon_trends(series: list[int], window_secs: int) -> list[tuple[str, str]]:
    """[(label, trend), ...] for the current interval plus each TREND_HORIZONS."""
    out = [("now", classify_horizon(series, 2))]
    for label, secs in TREND_HORIZONS:
        out.append((label, classify_horizon(series, windows_for_secs(secs, window_secs))))
    return out


def band_horizon_trends(history: list[WindowSummary], band: str,
                        window_secs: int) -> list[tuple[str, str]]:
    """Multi-horizon trends (now / 10m / 30m / 60m) for a band."""
    return _horizon_trends(band_spotter_series(history, band), window_secs)


def mm_horizon_trends(history: list[WindowSummary], band: str,
                      window_secs: int) -> list[tuple[str, str]]:
    """Multi-horizon trends for the tracked station on a band."""
    return _horizon_trends(mm_band_series(history, band), window_secs)


def aggregate_windows(summary: WindowSummary, history: list[WindowSummary],
                      avg_windows: int) -> WindowSummary:
    """Merge the last ``avg_windows`` committed windows into one summary.

    Cells are pooled (spot counts summed, distinct stations/spotters unioned,
    SNRs concatenated); the tracked-station observations are pooled the same
    way. The result *is* a :class:`WindowSummary`, so every renderer that takes
    a summary works on the 15-minute view unchanged. Falls back to the live
    snapshot before any window has been committed.
    """
    windows = _recent(history, avg_windows) or [summary]
    view = WindowSummary(start_time=windows[0].start_time,
                         end_time=windows[-1].end_time, mycall=summary.mycall)
    for w in windows:
        view.total_spots += w.total_spots
        view.total_uk_spots += w.total_uk_spots
        for key, cell in w.cells.items():
            c = view.cells.setdefault(key, CellStats())
            c.count += cell.count
            c.uk_stations |= cell.uk_stations
            c.spotters |= cell.spotters
            c.snrs += cell.snrs
        for key, obs in w.mm.items():
            o = view.mm.setdefault(key, MmObservation())
            o.spotters |= obs.spotters
            o.snrs += obs.snrs
            o.speeds += obs.speeds
            o.freqs += obs.freqs
        for cont, sk in w.skimmers.items():
            view.skimmers.setdefault(cont, set()).update(sk)
    return view


# --- reach-fraction metrics (activity normalisation) -----------------------

def _ewma(series: list[float], alpha: float) -> float | None:
    if not series:
        return None
    s = series[0]
    for x in series[1:]:
        s = alpha * x + (1.0 - alpha) * s
    return s


def per_window_reach(history: list[WindowSummary], band: str,
                     cont: str) -> list[float]:
    """Per-window reach fraction (UK heard in cont / UK active on band).

    Only windows where the band had UK activity contribute (so dead windows
    don't drag the smoothed value, and we never divide by zero).
    """
    out: list[float] = []
    for w in history:
        denom = w.band_active_uk(band)
        if denom <= 0:
            continue
        cell = w.cell(band, cont)
        num = cell.distinct_uk if cell else 0
        out.append(num / denom)
    return out


def smoothed_reach(history: list[WindowSummary], band: str, cont: str,
                   alpha: float = REACH_EWMA_ALPHA) -> float:
    """EWMA-smoothed reach fraction over the window history (0..1)."""
    return _ewma(per_window_reach(history, band, cont), alpha) or 0.0


def activity_confidence(view: WindowSummary, band: str) -> float:
    """Confidence (0..1) in a band's reach numbers from the active-UK sample."""
    n = view.band_active_uk(band)
    return n / (n + REACH_CONF_K) if n > 0 else 0.0


def coverage_factor(view: WindowSummary, cont: str) -> float:
    """Boost (1..CAP) for continents with thin skimmer coverage.

    A detection where few skimmers are listening means more than the same
    detection where hundreds are. Dense continents get factor 1.0 (no change).
    """
    sk = view.skimmer_count(cont)
    if sk <= 0:
        return 1.0
    return min(COVERAGE_BOOST_CAP, max(1.0, COVERAGE_REF_SKIMMERS / sk))


@dataclass
class ContRec:
    band: str
    reach: float          # smoothed reach fraction 0..1
    active_uk: int        # active-UK population on the band (denominator)
    count: int            # raw spot count in this cell (avg-window total)
    spotters: int         # distinct skimmers in this cell
    median_snr: float | None
    coverage: int         # active skimmers in the continent
    trend: str


@dataclass
class BandRec:
    band: str
    score: float
    trend: str
    active_uk: int
    dx_signal: float      # coverage-weighted sum of reach across DX continents
    best_cont: str | None
    best_reach: float


def _band_reach_signal(view: WindowSummary, history: list[WindowSummary],
                       band: str, alpha: float):
    """(dx_signal, best_cont, best_reach) for a band's DX reach."""
    dx_signal = 0.0
    best_cont, best_reach = None, 0.0
    for cont in DX_CONTINENTS:
        sr = smoothed_reach(history, band, cont, alpha)
        if sr <= 0:
            continue
        dx_signal += sr * coverage_factor(view, cont)
        if sr > best_reach:
            best_reach, best_cont = sr, cont
    return dx_signal, best_cont, best_reach


def score_bands(view: WindowSummary, history: list[WindowSummary],
                avg_windows: int, alpha: float = REACH_EWMA_ALPHA):
    """DX-scored bands, best first, ranked by activity-normalised reach.

    Score = coverage-weighted DX reach x activity-confidence x trend-weight, so a
    quiet-but-propagating band can outrank a busy-but-poorly-propagating one.
    Returns a list of :class:`BandRec`.
    """
    scored: list[BandRec] = []
    for band in view.active_bands():
        dx_signal, best_cont, best_reach = _band_reach_signal(
            view, history, band, alpha)
        if dx_signal <= 0:
            continue
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        conf = activity_confidence(view, band)
        score = dx_signal * conf * TREND_WEIGHT.get(trend, 1.0)
        scored.append(BandRec(band, score, trend, view.band_active_uk(band),
                              dx_signal, best_cont, best_reach))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored


def best_band_per_continent(view: WindowSummary,
                            history: list[WindowSummary], avg_windows: int,
                            alpha: float = REACH_EWMA_ALPHA):
    """Map each DX continent -> best :class:`ContRec`, or ``None`` if closed."""
    result: dict[str, ContRec | None] = {}
    for cont in DX_CONTINENTS:
        best = None  # (weighted_value, ContRec)
        for band in view.active_bands():
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            sr = smoothed_reach(history, band, cont, alpha)
            trend = classify_horizon(band_spotter_series(history, band),
                                     avg_windows)
            conf = activity_confidence(view, band)
            val = sr * coverage_factor(view, cont) * conf * \
                TREND_WEIGHT.get(trend, 1.0)
            rec = ContRec(band, sr, view.band_active_uk(band), cell.count,
                          cell.distinct_spotters, cell.median_snr,
                          view.skimmer_count(cont), trend)
            if best is None or val > best[0]:
                best = (val, rec)
        result[cont] = None if best is None else best[1]
    return result


def recommended_dx_band(view: WindowSummary, history: list[WindowSummary],
                        avg_windows: int,
                        alpha: float = REACH_EWMA_ALPHA) -> tuple[str, str, int] | None:
    """(band, continent, reach_pct_int) of the single best DX opportunity."""
    best = None
    for band in view.active_bands():
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        wgt = TREND_WEIGHT.get(trend, 1.0)
        conf = activity_confidence(view, band)
        for cont in DX_CONTINENTS:
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            sr = smoothed_reach(history, band, cont, alpha)
            val = sr * coverage_factor(view, cont) * conf * wgt
            if best is None or val > best[0]:
                best = (val, band, cont, round(sr * 100))
    if best is None:
        return None
    return best[1], best[2], best[3]


def mm_current_band(view: WindowSummary) -> str | None:
    """The band on which the tracked station has the most distinct spotters."""
    best_band = None
    best = -1
    for band in view.mm_bands():
        sp = view.mm_band_spotters(band)
        if sp > best:
            best = sp
            best_band = band
    return best_band

