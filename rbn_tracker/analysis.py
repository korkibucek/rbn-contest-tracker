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
    SHORT_TREND_WINDOWS,
    STEADY,
    TREND_HORIZONS,
    WindowSummary,
    band_spotter_series,
    classify_horizon,
    classify_trend,
    mm_band_series,
    windows_for_secs,
)

# Trend weighting for the recommendation engine: a band that is opening should
# outrank a higher-count band that is closing.
TREND_WEIGHT = {RISING: 1.6, NEW: 1.4, STEADY: 1.0, FADING: 0.45, GONE: 0.1}


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


def band_trend(history: list[WindowSummary], band: str,
               short_windows: int = SHORT_TREND_WINDOWS) -> str:
    """Responsive 'now' trend used for recommendations (recent windows only)."""
    series = band_spotter_series(history, band)
    return classify_trend(series[-short_windows:])


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


def band_dx_stats(summary: WindowSummary, band: str) -> tuple[int, int]:
    """(distinct spotters into DX continents, total DX spot count) for band."""
    spotters: set[str] = set()
    count = 0
    for cont in DX_CONTINENTS:
        cell = summary.cell(band, cont)
        if cell:
            spotters |= cell.spotters
            count += cell.count
    return len(spotters), count


def score_bands(summary: WindowSummary, history: list[WindowSummary]):
    """Return DX-scored bands, best first.

    Each entry: ``(score, band, dx_spotters, dx_count, trend)``.
    """
    scored = []
    for band in summary.active_bands():
        dx_spotters, dx_count = band_dx_stats(summary, band)
        if dx_spotters == 0 and dx_count == 0:
            continue
        trend = band_trend(history, band)
        weight = TREND_WEIGHT.get(trend, 1.0)
        score = (dx_spotters + 0.1 * dx_count) * weight
        scored.append((score, band, dx_spotters, dx_count, trend))
    scored.sort(reverse=True)
    return scored


def best_band_per_continent(summary: WindowSummary,
                            history: list[WindowSummary]):
    """Map each DX continent -> ``(band, cell, trend)`` or ``None`` if closed."""
    result: dict[str, tuple[str, object, str] | None] = {}
    for cont in DX_CONTINENTS:
        best = None  # (weighted_value, band, cell, trend)
        for band in summary.active_bands():
            cell = summary.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            trend = band_trend(history, band)
            val = cell.distinct_spotters * TREND_WEIGHT.get(trend, 1.0)
            if best is None or val > best[0]:
                best = (val, band, cell, trend)
        result[cont] = None if best is None else (best[1], best[2], best[3])
    return result


def recommended_dx_band(summary: WindowSummary,
                        history: list[WindowSummary]) -> tuple[str, str, int] | None:
    """(band, continent, spotters) of the single best DX opportunity, or None."""
    best = None
    for band in summary.active_bands():
        trend = band_trend(history, band)
        w = TREND_WEIGHT.get(trend, 1.0)
        for cont in DX_CONTINENTS:
            cell = summary.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            val = cell.distinct_spotters * w
            cand = (val, band, cont, cell.distinct_spotters)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None
    return best[1], best[2], best[3]


def mm_current_band(summary: WindowSummary) -> str | None:
    """The band on which the tracked station has the most distinct spotters."""
    best_band = None
    best = -1
    for band in summary.mm_bands():
        sp = summary.mm_band_spotters(band)
        if sp > best:
            best = sp
            best_band = band
    return best_band
