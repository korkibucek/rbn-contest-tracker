"""Human-readable report rendering: matrix, recommendations, MM1E section.

Pure standard-library text rendering with optional Unicode sparklines (ASCII
fallback when the output encoding can't represent them). ``rich`` is *not*
required; if present, the CLI may colourise the output, but every byte produced
here is plain text so it degrades gracefully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .bands import band_sort_key
from .continents import CONTINENTS
from .processing import (
    DX_CONTINENTS,
    FADING,
    GONE,
    NEW,
    RISING,
    STEADY,
    WindowSummary,
    band_spotter_series,
    cell_spotter_series,
    classify_trend,
    mm_band_series,
)

# Trend weighting for the recommendation engine: a band that is opening should
# outrank a higher-count band that is closing.
TREND_WEIGHT = {RISING: 1.6, NEW: 1.4, STEADY: 1.0, FADING: 0.45, GONE: 0.1}

_SPARK_UNICODE = "▁▂▃▄▅▆▇█"
_SPARK_ASCII = "_.-=+*#@"
_ARROW_UNICODE = {RISING: "↑", FADING: "↓", NEW: "✦", GONE: "✗", STEADY: "→"}
_ARROW_ASCII = {RISING: "^", FADING: "v", NEW: "+", GONE: "x", STEADY: "-"}

MATRIX_COLS = list(CONTINENTS)  # NA, SA, EU, AF, AS, OC


@dataclass
class RenderConfig:
    mycall: str = "MM1E"
    use_unicode: bool = True
    window_secs: int = 60


def sparkline(series: list[int], use_unicode: bool = True) -> str:
    if not series:
        return ""
    chars = _SPARK_UNICODE if use_unicode else _SPARK_ASCII
    lo, hi = min(series), max(series)
    if hi == lo:
        # Flat line -> mid glyph (or lowest if all zero).
        glyph = chars[0] if hi == 0 else chars[len(chars) // 2]
        return glyph * len(series)
    span = hi - lo
    out = []
    for v in series:
        idx = int((v - lo) / span * (len(chars) - 1) + 0.5)
        out.append(chars[idx])
    return "".join(out)


def arrow(trend: str, use_unicode: bool = True) -> str:
    table = _ARROW_UNICODE if use_unicode else _ARROW_ASCII
    return table.get(trend, "-" if not use_unicode else "→")


def _fmt_snr(snr: float | None) -> str:
    if snr is None:
        return "  -  "
    return f"{snr:+.0f}dB"


def _band_trend(history: list[WindowSummary], band: str) -> str:
    return classify_trend(band_spotter_series(history, band))


def _prev_now(series: list[int]) -> tuple[int, int]:
    cur = series[-1] if series else 0
    prev = series[-2] if len(series) >= 2 else 0
    return prev, cur


# --- Sections --------------------------------------------------------------

def _render_header(summary: WindowSummary, cfg: RenderConfig) -> list[str]:
    utc = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(summary.end_time))
    win = int(round(summary.end_time - summary.start_time))
    return [
        "=" * 78,
        f" RBN UK/IE PROPAGATION REPORT   {utc}   (window {win}s)",
        f" spots in window: {summary.total_spots:<5d}   "
        f"UK/IE spots: {summary.total_uk_spots:<5d}   "
        f"tracking: {cfg.mycall}",
        "=" * 78,
    ]


def _render_matrix(summary: WindowSummary, history: list[WindowSummary],
                   cfg: RenderConfig) -> list[str]:
    bands = summary.active_bands()
    lines = ["", "BAND x CONTINENT  (spots, distinct-spotters in parens)", ""]
    if not bands:
        lines.append("  (no UK/IE spots this window)")
        return lines

    col_w = 11
    head = f"{'band':<6}" + "".join(f"{c:>{col_w}}" for c in MATRIX_COLS)
    head += "   trend"
    lines.append(head)
    lines.append("-" * len(head))

    for band in bands:
        row = f"{band:<6}"
        for cont in MATRIX_COLS:
            cell = summary.cell(band, cont)
            if cell and cell.count:
                row += f"{cell.count:>4}({cell.distinct_spotters:>2}){'':>{col_w-8}}"
            else:
                row += f"{'.':>{col_w}}"
        series = band_spotter_series(history, band)
        trend = classify_trend(series)
        prev, cur = _prev_now(series)
        spark = sparkline(series, cfg.use_unicode)
        row += f"   {spark} {prev}->{cur} {arrow(trend, cfg.use_unicode)} {trend}"
        lines.append(row)
    return lines


def _band_dx_stats(summary: WindowSummary, band: str) -> tuple[int, int]:
    """(distinct spotters into DX continents, total DX spot count) for band."""
    spotters: set[str] = set()
    count = 0
    for cont in DX_CONTINENTS:
        cell = summary.cell(band, cont)
        if cell:
            spotters |= cell.spotters
            count += cell.count
    return len(spotters), count


def _render_recommendation(summary: WindowSummary,
                           history: list[WindowSummary],
                           cfg: RenderConfig) -> list[str]:
    lines = ["", "BAND RECOMMENDATION (working DX -- activity into non-EU)", ""]
    bands = summary.active_bands()

    # Score each band for DX, trend-weighted.
    scored = []
    for band in bands:
        dx_spotters, dx_count = _band_dx_stats(summary, band)
        if dx_spotters == 0 and dx_count == 0:
            continue
        trend = _band_trend(history, band)
        weight = TREND_WEIGHT.get(trend, 1.0)
        score = (dx_spotters + 0.1 * dx_count) * weight
        scored.append((score, band, dx_spotters, dx_count, trend))

    if not scored:
        lines.append("  No DX (non-EU) activity from UK/IE this window.")
        lines.append("  Either EU-only conditions, or thin skimmer coverage "
                     "into DX -- watch the trends.")
        return lines

    scored.sort(reverse=True)
    top = scored[0]
    lines.append(
        f"  TOP DX BAND: {top[1]}  "
        f"({top[2]} distinct DX spotters, {top[3]} spots, {top[4]})"
    )

    # Best band per open DX continent.
    lines.append("")
    lines.append("  Best band per continent:")
    for cont in DX_CONTINENTS:
        best = None
        for band in bands:
            cell = summary.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            trend = _band_trend(history, band)
            w = TREND_WEIGHT.get(trend, 1.0)
            val = cell.distinct_spotters * w
            cand = (val, band, cell, trend)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is None:
            lines.append(f"    {cont}: closed (no UK/IE spots heard there)")
            continue
        _val, band, cell, trend = best
        cser = cell_spotter_series(history, band, cont)
        prev, cur = _prev_now(cser)
        lines.append(
            f"    {cont}: {band}  "
            f"{cell.count} spots / {cell.distinct_spotters} spotters / "
            f"med {_fmt_snr(cell.median_snr)} / "
            f"{prev}->{cur} {arrow(trend, cfg.use_unicode)} {trend}"
        )
    return lines


def _recommended_dx_band(summary: WindowSummary,
                         history: list[WindowSummary]) -> tuple[str, str, int] | None:
    """Return (band, continent, spotters) of the single best DX opportunity."""
    best = None
    for band in summary.active_bands():
        trend = _band_trend(history, band)
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


def _render_mm(summary: WindowSummary, history: list[WindowSummary],
               cfg: RenderConfig) -> list[str]:
    me = cfg.mycall
    lines = ["", f"YOUR STATION -- {me} (how well you're getting out)", ""]

    if not summary.mm_spotted:
        lines.append(
            f"  {me} not spotted this window -- check you're calling CQ / "
            "band may be dead where you are."
        )
        return lines

    mm_current_band = None
    best_band_spotters = -1
    for band in summary.mm_bands():
        sp = summary.mm_band_spotters(band)
        if sp > best_band_spotters:
            best_band_spotters = sp
            mm_current_band = band

    for band in summary.mm_bands():
        series = mm_band_series(history, band)
        trend = classify_trend(series)
        prev, cur = _prev_now(series)
        total_sp = summary.mm_band_spotters(band)
        lines.append(
            f"  {me} {band}: {total_sp} distinct spotters total   "
            f"{sparkline(series, cfg.use_unicode)} {prev}->{cur} "
            f"{arrow(trend, cfg.use_unicode)} {trend}"
        )
        for cont in CONTINENTS:
            obs = summary.mm.get((band, cont))
            if not obs:
                continue
            speed = obs.typical_speed
            speed_s = f", ~{speed}wpm" if speed is not None else ""
            lines.append(
                f"      {cont}: {obs.distinct_spotters} spotters, "
                f"best {_fmt_snr(obs.best_snr)}, med {_fmt_snr(obs.median_snr)}"
                f"{speed_s}"
            )

    # QSY suggestion: compare my current band to the best DX opportunity.
    rec = _recommended_dx_band(summary, history)
    if rec and mm_current_band:
        rec_band, rec_cont, rec_sp = rec
        if rec_band != mm_current_band:
            mm_dx_sp, _ = _band_dx_stats(summary, mm_current_band)
            lines.append("")
            lines.append(
                f"  >> QSY SUGGESTION: you're strongest on {mm_current_band}, "
                f"but the cohort data says {rec_band} is the band into "
                f"{rec_cont} right now ({rec_sp} distinct spotters). "
                "Consider a move."
            )
    return lines


def _render_footer() -> list[str]:
    return [
        "",
        "-" * 78,
        " NOTE: RBN skimmer coverage is dense in NA/EU, sparse in AF/SA/OC.",
        " Low counts into those regions may reflect thin coverage, not a dead",
        " band -- lean on TRENDS and distinct-spotter counts, not absolute"
        " numbers.",
        "-" * 78,
    ]


def format_report(summary: WindowSummary, history: list[WindowSummary],
                  cfg: RenderConfig) -> str:
    """Render the full once-per-minute report as plain text."""
    lines: list[str] = []
    lines += _render_header(summary, cfg)
    lines += _render_matrix(summary, history, cfg)
    lines += _render_recommendation(summary, history, cfg)
    lines += _render_mm(summary, history, cfg)
    lines += _render_footer()
    return "\n".join(lines)
