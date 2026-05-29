"""Full-screen, `top`-style live viewer (curses, standard library).

The data model is built by :func:`build_frame` as a list of *styled lines*
(each line is a list of ``(text, style)`` segments). This keeps the layout pure
and unit-testable; :func:`run_tui` is the thin curses painter that maps styles
to colours and repaints in place. No third-party dependencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .analysis import (
    band_horizon_trends,
    best_band_per_continent,
    mm_current_band,
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
)
from .report import RenderConfig, arrow, sparkline

Segment = tuple[str, str]
Line = list[Segment]
Frame = list[Line]

MATRIX_COLS = list(CONTINENTS)

_TREND_STYLE = {
    RISING: "rising", FADING: "fading", STEADY: "steady", NEW: "new", GONE: "gone",
}


@dataclass
class TuiState:
    """Mutable view state shared with the curses loop."""

    source: str = "live"  # "live" or "replay"
    paused: bool = False
    spots_seen: int = 0
    skipped: int = 0
    connected: bool = False
    started_at: float = field(default_factory=time.time)
    now: float = field(default_factory=time.time)
    message: str = ""


def _trend_style(trend: str) -> str:
    return _TREND_STYLE.get(trend, "normal")


def _fmt_uptime(secs: float) -> str:
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_snr(snr: float | None) -> str:
    return "  -  " if snr is None else f"{snr:+.0f}dB"


def _horizon_segments(trends: list[tuple[str, str]], use_unicode: bool) -> Line:
    segs: Line = []
    for i, (label, trend) in enumerate(trends):
        if i:
            segs.append(("  ", "normal"))
        segs.append((f"{label} ", "dim"))
        segs.append((arrow(trend, use_unicode), _trend_style(trend)))
    return segs


# --- frame builder ---------------------------------------------------------

def build_frame(summary: WindowSummary, history: list[WindowSummary],
                cfg: RenderConfig, state: TuiState) -> Frame:
    uc = cfg.use_unicode
    frame: Frame = []

    # --- title bar ---
    utc = time.strftime("%H:%M:%SZ", time.gmtime(state.now))
    win = cfg.window_secs
    conn = "LIVE" if (state.source == "live" and state.connected) else (
        "CONNECTING" if state.source == "live" else "REPLAY")
    conn_style = "good" if conn == "LIVE" else ("warn" if conn == "CONNECTING" else "accent")
    title: Line = [
        (" RBN UK/IE CONTEST ", "title"),
        (f" {utc} ", "dim"),
        (f"up {_fmt_uptime(state.now - state.started_at)} ", "dim"),
        (conn, conn_style),
        (f"  win {win}s  ", "dim"),
        (f"spots/win {summary.total_spots} (UK {summary.total_uk_spots})  ", "normal"),
        (f"rx {state.spots_seen}", "dim"),
        (f"  tracking {cfg.mycall}", "accent"),
    ]
    if state.paused:
        title.append(("  [PAUSED]", "warn"))
    frame.append(title)
    frame.append([(_legend_text(uc), "dim")])
    frame.append([("", "normal")])

    bands = summary.active_bands()

    # --- matrix ---
    cross = "×" if uc else "x"
    dot = "·" if uc else "."
    frame.append([(f"BAND {cross} CONTINENT  ", "hdr"),
                  ("(spots, distinct spotters)", "dim")])
    col_w = 11
    head: Line = [(f"{'band':<6}", "dim")]
    for c in MATRIX_COLS:
        head.append((f"{c:>{col_w}}", "dim"))
    head.append(("   now", "dim"))
    frame.append(head)
    if not bands:
        frame.append([("  (no UK/IE spots in the current window)", "dim")])
    for band in bands:
        line: Line = [(f"{band:<6}", "accent")]
        for cont in MATRIX_COLS:
            cell = summary.cell(band, cont)
            if cell and cell.count:
                txt = f"{cell.count:>4}({cell.distinct_spotters:>2})"
                style = "good" if cont != "EU" else "normal"
                line.append((f"{txt:>{col_w}}", style))
            else:
                line.append((f"{dot:>{col_w}}", "dim"))
        now_trend = band_horizon_trends(history, band, cfg.window_secs)[0][1]
        line.append(("   ", "normal"))
        line.append((arrow(now_trend, uc), _trend_style(now_trend)))
        line.append((f" {now_trend}", _trend_style(now_trend)))
        frame.append(line)

    frame.append([("", "normal")])

    # --- trends (multi-horizon) ---
    frame.append([("BAND TRENDS  ", "hdr"),
                  ("distinct DX spotters: now / 10m / 30m / 60m", "dim")])
    for band in bands:
        series = band_spotter_series(history, band)
        spark = sparkline(series, uc)
        trends = band_horizon_trends(history, band, cfg.window_secs)
        line: Line = [(f"  {band:<5} ", "accent"), (f"{spark:<12} ", "normal")]
        line += _horizon_segments(trends, uc)
        frame.append(line)

    frame.append([("", "normal")])

    # --- recommendation ---
    frame.append([("RECOMMENDATION  ", "hdr"), ("work DX (non-EU)", "dim")])
    scored = score_bands(summary, history)
    if not scored:
        frame.append([("  No DX activity this window — EU-only or thin "
                       "coverage; watch the trends.", "dim")])
    else:
        top = scored[0]
        frame.append([("  TOP DX BAND: ", "normal"), (top[1], "good"),
                      (f"  {top[2]} spotters / {top[3]} spots  ", "normal"),
                      (top[4], _trend_style(top[4]))])
        for cont, best in best_band_per_continent(summary, history).items():
            if best is None:
                frame.append([(f"    {cont}: ", "dim"), ("closed", "fading")])
                continue
            band, cell, trend = best
            frame.append([
                (f"    {cont}: ", "dim"), (band, "accent"),
                (f"  {cell.count} sp / {cell.distinct_spotters} spotters / "
                 f"med {_fmt_snr(cell.median_snr)}  ", "normal"),
                (arrow(trend, uc), _trend_style(trend)),
                (f" {trend}", _trend_style(trend)),
            ])

    frame.append([("", "normal")])

    # --- MM / your station ---
    dash = "—" if uc else "-"
    frame.append([(f"YOUR STATION {dash} {cfg.mycall}  ", "hdr"),
                  ("(getting out)", "dim")])
    if not summary.mm_spotted:
        frame.append([(f"  {cfg.mycall} not spotted this window — check you're "
                       "calling CQ / band may be dead where you are.", "warn")])
    else:
        for band in summary.mm_bands():
            series = mm_band_series(history, band)
            trends = mm_horizon_trends(history, band, cfg.window_secs)
            total_sp = summary.mm_band_spotters(band)
            line: Line = [
                (f"  {cfg.mycall} {band}: ", "accent"),
                (f"{total_sp} spotters  ", "good"),
                (f"{sparkline(series, uc):<10} ", "normal"),
            ]
            line += _horizon_segments(trends, uc)
            frame.append(line)
            for cont in CONTINENTS:
                obs = summary.mm.get((band, cont))
                if not obs:
                    continue
                speed = obs.typical_speed
                speed_s = f", ~{speed}wpm" if speed is not None else ""
                frame.append([
                    (f"      {cont}: ", "dim"),
                    (f"{obs.distinct_spotters} spotters, best "
                     f"{_fmt_snr(obs.best_snr)}, med {_fmt_snr(obs.median_snr)}"
                     f"{speed_s}", "normal"),
                ])
        rec = recommended_dx_band(summary, history)
        current = mm_current_band(summary)
        if rec and current and rec[0] != current:
            frame.append([
                (f"  {'»' if uc else '>>'} QSY: ", "warn"),
                (f"you're strongest on {current}, but {rec[0]} is the band into "
                 f"{rec[1]} now ({rec[2]} spotters). Consider a move.", "normal"),
            ])

    return frame


def _legend_text(use_unicode: bool) -> str:
    a = lambda t: arrow(t, use_unicode)  # noqa: E731
    return (f" {a(RISING)} rising  {a(FADING)} fading  {a(STEADY)} steady  "
            f"{a(NEW)} new  {a(GONE)} gone   [q]uit [p]ause")


def flatten_frame(frame: Frame) -> str:
    """Render a frame to plain text (for tests / non-curses output)."""
    return "\n".join("".join(text for text, _ in line) for line in frame)


# --- curses painter --------------------------------------------------------

def run_tui(processor, cfg: RenderConfig, state: TuiState, lock,
            get_now=time.time, refresh_secs: float = 1.0,
            on_commit=None, stop_check=None, pre_render=None) -> None:
    """Run the curses event loop until 'q' or ``stop_check()`` is true.

    ``processor``  : SpotProcessor (filled by a background reader thread)
    ``lock``       : threading.Lock guarding the processor buffer
    ``on_commit``  : optional callback(summary, history) invoked each window
    ``stop_check`` : optional callable -> bool to request shutdown
    ``pre_render`` : optional callable(state) run each tick to refresh counters
    """
    import curses

    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.timeout(int(refresh_secs * 1000))
        _init_colors()
        next_commit = get_now() + cfg.window_secs
        last_frame: Frame = []
        while True:
            if stop_check and stop_check():
                break
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            if ch in (ord("p"), ord("P")):
                state.paused = not state.paused
            if ch == curses.KEY_RESIZE:
                stdscr.erase()

            now = get_now()
            state.now = now
            if pre_render:
                pre_render(state)
            if not state.paused:
                with lock:
                    processor.prune(now)
                    if now >= next_commit:
                        summary = processor.commit(now)
                        if on_commit:
                            on_commit(summary, list(processor.history))
                        next_commit += cfg.window_secs
                    snapshot = processor.snapshot(now)
                    history = list(processor.history)
                last_frame = build_frame(snapshot, history, cfg, state)
            _paint(stdscr, last_frame)

    curses.wrapper(_loop)


# curses colour handling -----------------------------------------------------
_PAIR_IDS: dict[str, int] = {}
_STYLE_DEF = {
    # style -> (fg, bold)
    "title": ("cyan", True),
    "hdr": ("cyan", True),
    "sub": ("white", False),
    "dim": ("white", False),
    "normal": ("white", False),
    "accent": ("yellow", True),
    "good": ("green", True),
    "warn": ("yellow", True),
    "rising": ("green", True),
    "fading": ("red", True),
    "steady": ("white", False),
    "new": ("cyan", True),
    "gone": ("red", False),
}


def _init_colors() -> None:
    import curses

    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    color_map = {
        "white": curses.COLOR_WHITE, "cyan": curses.COLOR_CYAN,
        "green": curses.COLOR_GREEN, "red": curses.COLOR_RED,
        "yellow": curses.COLOR_YELLOW,
    }
    pid = 1
    for style, (fg, _bold) in _STYLE_DEF.items():
        try:
            curses.init_pair(pid, color_map.get(fg, curses.COLOR_WHITE), bg)
            _PAIR_IDS[style] = pid
            pid += 1
        except curses.error:
            pass


def _attr_for(style: str):
    import curses

    if not curses.has_colors():
        return curses.A_BOLD if _STYLE_DEF.get(style, ("", False))[1] else curses.A_NORMAL
    attr = curses.color_pair(_PAIR_IDS.get(style, 0))
    if _STYLE_DEF.get(style, ("", False))[1]:
        attr |= curses.A_BOLD
    return attr


def _paint(stdscr, frame: Frame) -> None:
    import curses

    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    # Title bar gets a reverse-video full-width background on row 0.
    for y, line in enumerate(frame):
        if y >= max_y:
            break
        x = 0
        for text, style in line:
            if x >= max_x - 1:
                break
            attr = _attr_for(style)
            if y == 0:
                attr |= curses.A_REVERSE
            chunk = text[: max(0, max_x - 1 - x)]
            try:
                stdscr.addstr(y, x, chunk, attr)
            except curses.error:
                pass
            x += len(chunk)
        if y == 0 and x < max_x - 1:
            try:
                stdscr.addstr(y, x, " " * (max_x - 1 - x), _attr_for("title") | curses.A_REVERSE)
            except curses.error:
                pass
    stdscr.refresh()
