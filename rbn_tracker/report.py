"""Human-readable report rendering: matrix, recommendations, MM1E section.

Pure standard-library text rendering with optional Unicode sparklines (ASCII
fallback when the output encoding can't represent them). ``rich`` is *not*
required; if present, the CLI may colourise the output, but every byte produced
here is plain text so it degrades gracefully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .analysis import (
    DEFAULT_AVG_WINDOW_SECS,
    aggregate_windows,
    band_horizon_trends,
    best_band_per_continent,
    display_bands,
    minutes_label,
    mm_horizon_trends,
    recommended_dx_band,
    score_bands,
)
from .continents import CONTINENTS
from .processing import (
    FADING,
    GONE,
    NEW,
    RISING,
    STEADY,
    WindowSummary,
    band_spotter_series,
    mm_band_series,
    windows_for_secs,
)
from .runstate import RunStatus, compute_run_status, idle_tx_suggestion

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
    avg_window_secs: int = DEFAULT_AVG_WINDOW_SECS  # matrix/rec/your-station view
    category_key: str = "single"  # single | m2 | mm

    @property
    def avg_windows(self) -> int:
        return windows_for_secs(self.avg_window_secs, self.window_secs)

    @property
    def avg_label(self) -> str:
        return minutes_label(self.avg_window_secs)


SPARK_MAX_POINTS = 24  # cap width; history can hold an hour of windows


def sparkline(series: list[int], use_unicode: bool = True,
              max_points: int = SPARK_MAX_POINTS) -> str:
    if not series:
        return ""
    if max_points and len(series) > max_points:
        series = series[-max_points:]  # most recent points only
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


def _horizon_strip(trends: list[tuple[str, str]], use_unicode: bool) -> str:
    """Render multi-horizon trends as e.g. 'now ↑  10min ↑  30min →  60min ↓'."""
    return "  ".join(f"{label} {arrow(trend, use_unicode)}"
                     for label, trend in trends)


def _legend(use_unicode: bool) -> str:
    a = lambda t: arrow(t, use_unicode)  # noqa: E731
    return (f"({a(RISING)} rising  {a(FADING)} fading  {a(STEADY)} steady  "
            f"{a(NEW)} new  {a(GONE)} gone)")


# --- Sections --------------------------------------------------------------

def _render_header(view: WindowSummary, cfg: RenderConfig) -> list[str]:
    utc = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(view.end_time))
    return [
        "=" * 78,
        f" RBN UK/IE PROPAGATION REPORT   {utc}   (last {cfg.avg_label})",
        f" spots: {view.total_spots:<5d}   "
        f"UK/IE spots: {view.total_uk_spots:<5d}   "
        f"tracking: {cfg.mycall}",
        "=" * 78,
    ]


def _render_matrix(view: WindowSummary, history: list[WindowSummary],
                   cfg: RenderConfig) -> list[str]:
    bands = display_bands(view, history)
    lines = ["", f"BAND x CONTINENT  (spots, distinct-spotters over last "
             f"{cfg.avg_label})", ""]
    if not bands:
        lines.append("  (no UK/IE spots in the last "
                     f"{cfg.avg_label} or recent history)")
        return lines

    col_w = 11
    head = f"{'band':<6}" + "".join(f"{c:>{col_w}}" for c in MATRIX_COLS)
    head += "   now"
    lines.append(head)
    lines.append("-" * len(head))

    for band in bands:
        row = f"{band:<6}"
        for cont in MATRIX_COLS:
            cell = view.cell(band, cont)
            if cell and cell.count:
                row += f"{cell.count:>4}({cell.distinct_spotters:>2}){'':>{col_w-8}}"
            else:
                row += f"{'.':>{col_w}}"
        now_trend = band_horizon_trends(history, band, cfg.window_secs)[0][1]
        row += f"   {arrow(now_trend, cfg.use_unicode)} {now_trend}"
        lines.append(row)
    return lines


def _render_trends(view: WindowSummary, history: list[WindowSummary],
                   cfg: RenderConfig) -> list[str]:
    bands = display_bands(view, history)
    lines = ["",
             "BAND TRENDS (distinct DX spotters)   " + _legend(cfg.use_unicode),
             ""]
    if not bands:
        return lines
    for band in bands:
        series = band_spotter_series(history, band)
        spark = sparkline(series, cfg.use_unicode)
        trends = band_horizon_trends(history, band, cfg.window_secs)
        lines.append(
            f"  {band:<5} {spark:<10}  {_horizon_strip(trends, cfg.use_unicode)}"
        )
    return lines


def _render_recommendation(view: WindowSummary,
                           history: list[WindowSummary],
                           cfg: RenderConfig) -> list[str]:
    lines = ["", f"BAND RECOMMENDATION (working DX into non-EU, last "
             f"{cfg.avg_label})", ""]

    scored = score_bands(view, history, cfg.avg_windows)
    if not scored:
        lines.append(f"  No DX (non-EU) activity from UK/IE in the last "
                     f"{cfg.avg_label}.")
        lines.append("  Either EU-only conditions, or thin skimmer coverage "
                     "into DX -- watch the trends.")
        return lines

    top = scored[0]
    lines.append(
        f"  TOP DX BAND: {top[1]}  "
        f"({top[2]} distinct DX spotters, {top[3]} spots, {top[4]})"
    )

    # Best band per open DX continent.
    lines.append("")
    lines.append("  Best band per continent:")
    for cont, best in best_band_per_continent(view, history, cfg.avg_windows).items():
        if best is None:
            lines.append(f"    {cont}: closed (no UK/IE spots heard there)")
            continue
        band, cell, trend = best
        lines.append(
            f"    {cont}: {band}  "
            f"{cell.count} spots / {cell.distinct_spotters} spotters / "
            f"med {_fmt_snr(cell.median_snr)} / "
            f"{arrow(trend, cfg.use_unicode)} {trend}"
        )
    return lines


def _render_run_status(status: RunStatus, open_dx_bands: list[str],
                       cfg: RenderConfig) -> list[str]:
    me = cfg.mycall
    lines = [f"  RUN [{status.category_name}, {status.max_tx} TX]:"]
    if status.running_bands:
        runs = ", ".join(
            f"{b} @ {status.frequencies[b]:.1f}" if b in status.frequencies
            else b
            for b in status.running_bands
        )
        lines.append(f"    running CQ on: {runs}")
    else:
        lines.append("    no CQ run detected -- S&P, between bands, or off air")
    # Single-op sanity: shouldn't be running two bands at once.
    if status.max_tx == 1 and status.running_count > 1:
        lines.append(f"    running {status.running_count} bands at once "
                     "(single TX) -- band change in progress?")
    for frm, to in status.qsy:
        lines.append(f"    band change: {frm} -> {to} (run moved)")
    for band, mins in status.sp_or_off:
        lines.append(f"    {band}: no CQ for ~{mins}m -- gone S&P or off this band")
    if status.max_tx >= 2:
        lines.append(f"    running {status.running_count}/{status.max_tx} "
                     "transmitters")
        idle = idle_tx_suggestion(status, open_dx_bands)
        if idle:
            lines.append(f"    >> {idle}")
        if status.category_key == "m2" and \
                status.band_changes_last_hour > 0:
            lines.append(f"    band changes last hr: "
                         f"{status.band_changes_last_hour} "
                         "(M/2 limit 8/hr per TX)")
    return lines


def _render_mm(view: WindowSummary, history: list[WindowSummary],
               cfg: RenderConfig, run_status: RunStatus) -> list[str]:
    me = cfg.mycall
    lines = ["", f"YOUR STATION -- {me} (getting out, last {cfg.avg_label})", ""]

    open_dx_bands = [s[1] for s in score_bands(view, history, cfg.avg_windows)]
    lines += _render_run_status(run_status, open_dx_bands, cfg)
    lines.append("")

    if not view.mm_spotted:
        lines.append(
            f"  {me} not spotted in the last {cfg.avg_label} -- check you're "
            "calling CQ / band may be dead where you are."
        )
        return lines

    for band in view.mm_bands():
        series = mm_band_series(history, band)
        trends = mm_horizon_trends(history, band, cfg.window_secs)
        total_sp = view.mm_band_spotters(band)
        lines.append(
            f"  {me} {band}: {total_sp} distinct spotters   "
            f"{sparkline(series, cfg.use_unicode)}  "
            f"{_horizon_strip(trends, cfg.use_unicode)}"
        )
        for cont in CONTINENTS:
            obs = view.mm.get((band, cont))
            if not obs:
                continue
            speed = obs.typical_speed
            speed_s = f", ~{speed}wpm" if speed is not None else ""
            lines.append(
                f"      {cont}: {obs.distinct_spotters} spotters, "
                f"best {_fmt_snr(obs.best_snr)}, med {_fmt_snr(obs.median_snr)}"
                f"{speed_s}"
            )

    # QSY suggestion: compare where I'm actually running now to the best DX
    # opportunity (only meaningful when running a single band).
    rec = recommended_dx_band(view, history, cfg.avg_windows)
    if rec and len(run_status.running_bands) == 1:
        cur = run_status.running_bands[0]
        rec_band, rec_cont, rec_sp = rec
        if rec_band != cur:
            lines.append("")
            lines.append(
                f"  >> QSY SUGGESTION: you're running {cur}, but the cohort "
                f"data says {rec_band} is the band into {rec_cont} "
                f"({rec_sp} distinct spotters). Consider a move."
            )
    return lines


def _num(n: int | None) -> str:
    return "?" if n is None else f"{n:,}"


def _delta_str(d_q: int | None, d_m: int | None, d_s: int | None) -> str:
    if d_q is None and d_m is None and d_s is None:
        return "--"
    parts = []
    if d_q is not None:
        parts.append(f"{d_q:+d}Q")
    if d_m is not None:
        parts.append(f"{d_m:+d}M")
    if d_s is not None:
        parts.append(f"{d_s/1000:+.1f}k" if abs(d_s) >= 1000 else f"{d_s:+d}")
    return " ".join(parts)


def _run_str(run, now: float) -> str:
    if run is None:
        return "(no CQ/S&P)"
    return f"{run.freq_khz:.1f} {run.band}"


def _render_opponents(view_op, now: float) -> list[str]:
    title = (f"OPPONENTS (+/-{view_op.window}, {view_op.category_name}) "
             f"-- {view_op.source_label}")
    lines = ["", title, ""]
    if not view_op.entries:
        lines.append(f"  {view_op.message or 'no opponents'}")
        return lines
    lines.append(f"  {'call':<11} {'QSOs':>6} {'Mults':>6} {'Score':>12}   "
                 f"{'vs you':<18} run")
    for e in view_op.entries:
        mark = ">" if e.is_me else " "
        name = f"{e.call} (you)" if e.is_me else e.call
        lines.append(
            f"{mark} {name:<11} {_num(e.qsos):>6} {_num(e.mults):>6} "
            f"{_num(e.score):>12}   "
            f"{_delta_str(e.d_qsos, e.d_mults, e.d_score):<18} "
            f"{_run_str(e.run, now)}"
        )
    if view_op.message:
        lines.append(f"  ({view_op.message})")
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
                  cfg: RenderConfig, opponents=None) -> str:
    """Render the full report as plain text over the averaging-window view."""
    view = aggregate_windows(summary, history, cfg.avg_windows)
    run_status = compute_run_status(summary, history, cfg.window_secs,
                                    cfg.category_key)
    lines: list[str] = []
    lines += _render_header(view, cfg)
    lines += _render_matrix(view, history, cfg)
    lines += _render_trends(view, history, cfg)
    lines += _render_recommendation(view, history, cfg)
    lines += _render_mm(view, history, cfg, run_status)
    if opponents is not None and opponents.enabled:
        lines += _render_opponents(opponents, time.time())
    lines += _render_footer()
    return "\n".join(lines)
