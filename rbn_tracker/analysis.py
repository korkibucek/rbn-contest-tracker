"""Shared recommendation / scoring logic used by both the text report and TUI.

Keeping this in one place means the plain-text report and the full-screen viewer
can never drift apart in how they rank bands or pick the QSY suggestion.
"""

from __future__ import annotations

from .bands import band_sort_key
from .processing import (
    DX_CONTINENTS,
    FADING,
    GONE,
    NEW,
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
    return view


def _band_dx_stats(view: WindowSummary, band: str) -> tuple[int, int]:
    """(distinct DX spotters, DX spot count) for a band in the aggregated view."""
    spotters: set[str] = set()
    count = 0
    for cont in DX_CONTINENTS:
        cell = view.cell(band, cont)
        if cell:
            spotters |= cell.spotters
            count += cell.count
    return len(spotters), count


def score_bands(view: WindowSummary, history: list[WindowSummary],
                avg_windows: int):
    """DX-scored bands, best first, over the aggregated view.

    Each entry: ``(score, band, dx_spotters, dx_count, trend)`` where the counts
    are totals over the averaging window and ``trend`` is the band's trajectory
    over the same span.
    """
    scored = []
    for band in view.active_bands():
        dx_spotters, dx_count = _band_dx_stats(view, band)
        if dx_spotters == 0 and dx_count == 0:
            continue
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        score = (dx_spotters + 0.1 * dx_count) * TREND_WEIGHT.get(trend, 1.0)
        scored.append((score, band, dx_spotters, dx_count, trend))
    scored.sort(reverse=True)
    return scored


def best_band_per_continent(view: WindowSummary,
                            history: list[WindowSummary], avg_windows: int):
    """Map each DX continent -> ``(band, cell, trend)`` or ``None`` if closed."""
    result: dict[str, tuple | None] = {}
    for cont in DX_CONTINENTS:
        best = None  # (weighted_value, band, cell, trend)
        for band in view.active_bands():
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            trend = classify_horizon(band_spotter_series(history, band),
                                     avg_windows)
            val = cell.distinct_spotters * TREND_WEIGHT.get(trend, 1.0)
            if best is None or val > best[0]:
                best = (val, band, cell, trend)
        result[cont] = None if best is None else (best[1], best[2], best[3])
    return result


def recommended_dx_band(view: WindowSummary, history: list[WindowSummary],
                        avg_windows: int) -> tuple[str, str, int] | None:
    """(band, continent, spotters) of the single best DX opportunity."""
    best = None
    for band in view.active_bands():
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        wgt = TREND_WEIGHT.get(trend, 1.0)
        for cont in DX_CONTINENTS:
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            val = cell.distinct_spotters * wgt
            if best is None or val > best[0]:
                best = (val, band, cont, cell.distinct_spotters)
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

