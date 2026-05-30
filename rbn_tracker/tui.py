"""Full-screen, `top`-style live viewer (curses, standard library).

Layout model
------------
:func:`build_frame` returns a list of *styled lines* (each line a list of
``(text, style)`` segments) made of a header bar plus a stack of **bordered
panels**, sized to a given width. :func:`build_footer` returns the help/legend
bar. :func:`run_tui` is the thin curses painter: it pins the header to the top
row, the footer to the bottom row, and paints the panels in between, repainting
in place. Keeping layout pure (segments, no curses) means it stays unit-testable
via :func:`flatten_frame`. No third-party dependencies; degrades to ASCII.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .analysis import (
    aggregate_windows,
    band_horizon_trends,
    best_band_per_continent,
    display_bands,
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
from .runstate import compute_run_status, idle_tx_suggestion

Segment = tuple[str, str]
Line = list[Segment]
Frame = list[Line]

MATRIX_COLS = list(CONTINENTS)
MIN_WIDTH = 44
MAX_WIDTH = 120
SPARK_W = 16

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


# --- small helpers ---------------------------------------------------------

def _trend_style(trend: str) -> str:
    return _TREND_STYLE.get(trend, "normal")


def _fmt_uptime(secs: float) -> str:
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_snr(snr: float | None) -> str:
    return "  - " if snr is None else f"{snr:+.0f}dB"


def _fmt_num(n) -> str:
    return "?" if n is None else f"{n:,}"


def _seg_len(line: Line) -> int:
    return sum(len(t) for t, _ in line)


def _fit(line: Line, target: int) -> Line:
    """Clip/pad a line's segments to exactly ``target`` visible characters."""
    out: Line = []
    used = 0
    for text, style in line:
        if used >= target:
            break
        take = text[: target - used]
        if take:
            out.append((take, style))
            used += len(take)
    if used < target:
        out.append((" " * (target - used), "normal"))
    return out


def _box(uc: bool) -> dict:
    if uc:
        return dict(tl="┌", tr="┐", bl="└", br="┘", h="─", v="│")
    return dict(tl="+", tr="+", bl="+", br="+", h="-", v="|")


def _vbar(uc: bool) -> str:
    return "│" if uc else "|"


def _panel(title: Line, subtitle: str, body: list[Line], width: int,
           uc: bool) -> list[Line]:
    """Wrap ``body`` lines in a titled border box ``width`` columns wide."""
    b = _box(uc)
    out: list[Line] = []

    prefix = f"{b['tl']}{b['h']} "
    title_plain = "".join(t for t, _ in title)
    sub = f" {b['h']} {subtitle} " if subtitle else f"{b['h']}"
    used = len(prefix) + len(title_plain) + len(sub)
    fill = max(0, width - used - 1)
    out.append([(prefix, "border")] + list(title)
               + [(sub, "dim"), (b["h"] * fill, "border"), (b["tr"], "border")])

    inner = width - 4
    for line in body:
        out.append([(b["v"] + " ", "border")] + _fit(line, inner)
                   + [(" " + b["v"], "border")])

    out.append([(b["bl"] + b["h"] * (width - 2) + b["br"], "border")])
    return out


def _hr(width: int, uc: bool) -> Line:
    """A thin inner divider line for use inside a panel body."""
    return [(("┄" if uc else "-") * (width - 4), "dim")]


def _horizon_segments(trends: list[tuple[str, str]], use_unicode: bool) -> Line:
    segs: Line = []
    for i, (label, trend) in enumerate(trends):
        if i:
            segs.append(("  ", "normal"))
        segs.append((f"{label} ", "dim"))
        segs.append((arrow(trend, use_unicode), _trend_style(trend)))
    return segs


# --- section bodies --------------------------------------------------------

def _matrix_body(view, history, cfg, bands, span, uc, width) -> list[Line]:
    dot = "·" if uc else "."
    inner = width - 4
    band_w, now_w = 5, 10
    col_w = max(7, (inner - band_w - now_w) // len(MATRIX_COLS))

    head: Line = [(f"{'band':<{band_w}}", "dim")]
    for c in MATRIX_COLS:
        head.append((f"{c:>{col_w}}", "dim"))
    head.append((f"{'now':>{now_w}}", "dim"))
    rows: list[Line] = [head]

    if not bands:
        rows.append([(f"no UK/IE spots in the last {span} or recent history",
                      "dim")])
        return rows

    for band in bands:
        line: Line = [(f"{band:<{band_w}}", "accent")]
        for cont in MATRIX_COLS:
            cell = view.cell(band, cont)
            if cell and cell.count:
                txt = f"{cell.count}({cell.distinct_spotters})"
                style = "good" if cont != "EU" else "normal"
                line.append((f"{txt:>{col_w}}", style))
            else:
                line.append((f"{dot:>{col_w}}", "dim"))
        nt = band_horizon_trends(history, band, cfg.window_secs)[0][1]
        now_plain = f"{arrow(nt, uc)} {nt}"
        line.append((" " * max(1, now_w - len(now_plain)), "dim"))
        line.append((arrow(nt, uc), _trend_style(nt)))
        line.append((f" {nt}", _trend_style(nt)))
        rows.append(line)
    return rows


def _trends_body(history, cfg, bands, uc) -> list[Line]:
    if not bands:
        return [[("-", "dim")]]
    rows: list[Line] = []
    for band in bands:
        series = band_spotter_series(history, band)
        spark = sparkline(series, uc)
        trends = band_horizon_trends(history, band, cfg.window_secs)
        line: Line = [(f"{band:<5} ", "accent"), (f"{spark:<{SPARK_W}} ", "normal")]
        line += _horizon_segments(trends, uc)
        rows.append(line)
    return rows


def _rec_body(view, history, cfg, scored, span, uc) -> list[Line]:
    if not scored:
        return [[(f"no DX reach in the last {span} — EU-only or thin "
                  "coverage; watch the trends.", "dim")]]
    top = scored[0]
    bc = top.best_cont or "DX"
    rows: list[Line] = [[
        ("TOP DX BAND  ", "dim"), (top.band, "good"),
        (f"   best reach {bc} {top.best_reach*100:.0f}% of {top.active_uk} "
         "active   ", "normal"),
        (top.trend, _trend_style(top.trend)),
    ]]
    for cont, best in best_band_per_continent(view, history,
                                              cfg.avg_windows).items():
        if best is None:
            rows.append([(f"  {cont}  ", "dim"), ("closed", "fading")])
            continue
        rows.append([
            (f"  {cont}  ", "dim"), (f"{best.band:<4}", "accent"),
            (f" {best.reach*100:>3.0f}% of {best.active_uk:<3}", "good"),
            (f"  {best.count}sp  med {_fmt_snr(best.median_snr)}  "
             f"cov~{best.coverage}  ", "normal"),
            (arrow(best.trend, uc), _trend_style(best.trend)),
            (f" {best.trend}", _trend_style(best.trend)),
        ])
    return rows


def _station_body(summary, view, history, cfg, scored, span, uc,
                  width) -> list[Line]:
    rows: list[Line] = []
    run_status = compute_run_status(summary, history, cfg.window_secs,
                                    cfg.category_key)
    open_dx_bands = [r.band for r in scored] if scored else []
    arrow_to = "→" if uc else "->"

    run_line: Line = [(f"RUN  [{run_status.category_name}, "
                       f"{run_status.max_tx} TX]   ", "dim"),
                      ("CQ on ", "dim")]
    if run_status.running_bands:
        for i, band in enumerate(run_status.running_bands):
            if i:
                run_line.append((", ", "dim"))
            run_line.append((band, "good"))
            if band in run_status.frequencies:
                run_line.append((f" @ {run_status.frequencies[band]:.1f}",
                                 "accent"))
    else:
        run_line.append(("nothing", "warn"))
    rows.append(run_line)

    if run_status.max_tx == 1 and run_status.running_count > 1:
        rows.append([(f"  running {run_status.running_count} bands at once "
                      "(single TX) — band change in progress?", "warn")])
    for frm, to in run_status.qsy:
        rows.append([("  band change  ", "dim"),
                     (f"{frm} {arrow_to} {to}", "new"), ("  (run moved)", "dim")])
    for band, mins in run_status.sp_or_off:
        rows.append([(f"  {band}  ", "dim"),
                     (f"no CQ for ~{mins}m — gone S&P or off this band",
                      "fading")])
    if run_status.max_tx >= 2:
        rows.append([(f"  transmitters in use  "
                      f"{run_status.running_count}/{run_status.max_tx}", "dim")])
        idle = idle_tx_suggestion(run_status, open_dx_bands)
        if idle:
            rows.append([("  " + ("» " if uc else ">> "), "warn"),
                         (idle, "warn")])
        if run_status.category_key == "m2" and run_status.band_changes_last_hour:
            rows.append([(f"  band changes last hr  "
                          f"{run_status.band_changes_last_hour} "
                          "(M/2 limit 8/hr per TX)", "dim")])

    rows.append(_hr(width, uc))

    if not view.mm_spotted:
        rows.append([(f"not spotted in the last {span} — check you're calling "
                      "CQ / band may be dead where you are.", "warn")])
        return rows

    for band in view.mm_bands():
        series = mm_band_series(history, band)
        trends = mm_horizon_trends(history, band, cfg.window_secs)
        total_sp = view.mm_band_spotters(band)
        line: Line = [
            (f"{band:<4} ", "accent"),
            (f"{total_sp:>2} spotters  ", "good"),
            (f"{sparkline(series, uc):<10} ", "normal"),
        ]
        line += _horizon_segments(trends, uc)
        rows.append(line)
        for cont in CONTINENTS:
            obs = view.mm.get((band, cont))
            if not obs:
                continue
            speed = obs.typical_speed
            speed_s = f", ~{speed}wpm" if speed is not None else ""
            rows.append([
                (f"   {cont}  ", "dim"),
                (f"{obs.distinct_spotters} spotters, best "
                 f"{_fmt_snr(obs.best_snr)}, med {_fmt_snr(obs.median_snr)}"
                 f"{speed_s}", "normal"),
            ])
    rec = recommended_dx_band(view, history, cfg.avg_windows)
    if rec and len(run_status.running_bands) == 1 \
            and rec[0] != run_status.running_bands[0]:
        cur = run_status.running_bands[0]
        rows.append(_hr(width, uc))
        rows.append([
            (("» " if uc else ">> "), "warn"), ("QSY  ", "warn"),
            (f"you're running {cur}, but {rec[0]} is the band into "
             f"{rec[1]} ({rec[2]}% reach). Consider a move.", "normal"),
        ])
    return rows


def _opponents_body(opponents, uc) -> list[Line]:
    if not opponents.entries:
        return [[(opponents.message or "no opponents", "dim")]]
    rows: list[Line] = [[
        (f"{'':2}{'call':<11}{'QSOs':>7}{'Mult':>6}{'Score':>12}"
         f"  {'vs you':<16} run", "dim")]]
    for e in opponents.entries:
        rows.append(_opponent_row(e, uc))
    if opponents.message:
        rows.append([(opponents.message, "dim")])
    return rows


def _opponent_row(e, uc: bool) -> Line:
    name = f"{e.call} (you)" if e.is_me else e.call
    name_style = "accent" if e.is_me else "normal"
    if e.is_me or e.d_score is None:
        delta_txt = ("you" if e.is_me else "?")
        delta_style = "dim"
    else:
        ds = e.d_score
        delta_style = "fading" if ds > 0 else ("good" if ds < 0 else "steady")
        dq = f"{e.d_qsos:+d}Q " if e.d_qsos is not None else ""
        dm = f"{e.d_mults:+d}M " if e.d_mults is not None else ""
        dsr = f"{ds/1000:+.1f}k" if abs(ds) >= 1000 else f"{ds:+d}"
        delta_txt = f"{dq}{dm}{dsr}"
    if e.run is not None:
        run_txt, run_style = f"{e.run.freq_khz:.1f} {e.run.band}", "good"
    else:
        run_txt, run_style = "(no CQ)", "dim"
    marker = ">" if e.is_me else " "
    return [
        (f"{marker} ", "accent"),
        (f"{name:<11}", name_style),
        (f"{_fmt_num(e.qsos):>7}", "normal"),
        (f"{_fmt_num(e.mults):>6}", "normal"),
        (f"{_fmt_num(e.score):>12}", "normal"),
        (f"  {delta_txt:<16}", delta_style),
        (run_txt, run_style),
    ]


# --- header / footer bars --------------------------------------------------

def _header_bar(cfg, state, view, span, uc) -> Line:
    vb = f" {_vbar(uc)} "
    utc = time.strftime("%H:%M:%SZ", time.gmtime(state.now))
    conn = "LIVE" if (state.source == "live" and state.connected) else (
        "CONNECTING" if state.source == "live" else "REPLAY")
    conn_style = ("good" if conn == "LIVE"
                  else "warn" if conn == "CONNECTING" else "accent")
    bar: Line = [
        (" RBN UK/IE CONTEST ", "title"),
        (vb, "dim"), (utc, "normal"),
        (vb, "dim"), (f"up {_fmt_uptime(state.now - state.started_at)}", "normal"),
        (vb, "dim"), (conn, conn_style),
        (vb, "dim"), (f"last {span}", "normal"),
        (vb, "dim"), (f"spots {view.total_spots} (UK {view.total_uk_spots})",
                      "normal"),
        (vb, "dim"), (cfg.mycall, "accent"),
    ]
    if state.paused:
        bar += [(vb, "dim"), ("PAUSED", "warn")]
    return bar


def build_footer(cfg, state, uc) -> Line:
    a = lambda t: arrow(t, uc)  # noqa: E731
    vb = f"  {_vbar(uc)}  "
    return [
        (" ", "dim"),
        (a(RISING), "rising"), (" rise ", "dim"),
        (a(FADING), "fading"), (" fade ", "dim"),
        (a(STEADY), "steady"), (" steady ", "dim"),
        (a(NEW), "new"), (" new ", "dim"),
        (a(GONE), "gone"), (" gone", "dim"),
        (vb, "dim"), ("[q]", "accent"), (" quit  ", "normal"),
        ("[p]", "accent"), (" pause", "normal"),
        (vb, "dim"), (state.source, "dim"),
    ]


# --- frame builder ---------------------------------------------------------

def build_frame(summary: WindowSummary, history: list[WindowSummary],
                cfg: RenderConfig, state: TuiState, opponents=None,
                width: int = 78) -> Frame:
    uc = cfg.use_unicode
    width = max(MIN_WIDTH, min(width, MAX_WIDTH))
    view = aggregate_windows(summary, history, cfg.avg_windows)
    span = cfg.avg_label
    cross = "×" if uc else "x"
    bands = display_bands(view, history)
    scored = score_bands(view, history, cfg.avg_windows)

    frame: Frame = [_header_bar(cfg, state, view, span, uc), [("", "normal")]]

    frame += _panel([("BAND ", "hdr"), (cross, "hdr"), (" CONTINENT", "hdr")],
                    f"spots(spotters) · last {span}" if uc
                    else f"spots(spotters) - last {span}",
                    _matrix_body(view, history, cfg, bands, span, uc, width),
                    width, uc)
    frame.append([("", "normal")])

    frame += _panel([("BAND TRENDS", "hdr")], "now / 10 / 30 / 60 min",
                    _trends_body(history, cfg, bands, uc), width, uc)
    frame.append([("", "normal")])

    frame += _panel([("RECOMMENDATION", "hdr")],
                    f"work DX · reach over last {span}" if uc
                    else f"work DX - reach over last {span}",
                    _rec_body(view, history, cfg, scored, span, uc), width, uc)
    frame.append([("", "normal")])

    frame += _panel([("YOUR STATION  ", "hdr"), (cfg.mycall, "accent")],
                    f"getting out · last {span}" if uc
                    else f"getting out - last {span}",
                    _station_body(summary, view, history, cfg, scored, span,
                                  uc, width),
                    width, uc)

    if opponents is not None and opponents.enabled:
        frame.append([("", "normal")])
        pm = "±" if uc else "+/-"
        sep = "·" if uc else "-"
        frame += _panel([("OPPONENTS", "hdr")],
                        f"{pm}{opponents.window}, {opponents.category_name} "
                        f"{sep} {opponents.source_label}",
                        _opponents_body(opponents, uc), width, uc)
    return frame


def flatten_frame(frame: Frame) -> str:
    """Render a frame to plain text (for tests / non-curses output)."""
    return "\n".join("".join(text for text, _ in line) for line in frame)


# --- curses painter --------------------------------------------------------

def run_tui(processor, cfg: RenderConfig, state: TuiState, lock,
            get_now=time.time, refresh_secs: float = 1.0,
            on_commit=None, stop_check=None, pre_render=None,
            opponents=None) -> None:
    """Run the curses event loop until 'q' or ``stop_check()`` is true."""
    import curses

    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.timeout(int(refresh_secs * 1000))
        _init_colors()
        next_commit = get_now() + cfg.window_secs
        frozen = None  # (snapshot, history, op_view) -- kept while paused
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
            if opponents is not None:
                opponents.refresh(now)
            if not state.paused or frozen is None:
                op_view = opponents.view(now) if opponents is not None else None
                with lock:
                    processor.prune(now)
                    if now >= next_commit:
                        summary = processor.commit(now)
                        if on_commit:
                            on_commit(summary, list(processor.history))
                        next_commit += cfg.window_secs
                    snapshot = processor.snapshot(now)
                    history = list(processor.history)
                frozen = (snapshot, history, op_view)

            snapshot, history, op_view = frozen
            max_y, max_x = stdscr.getmaxyx()
            frame = build_frame(snapshot, history, cfg, state, op_view,
                                width=max_x)
            footer = build_footer(cfg, state, cfg.use_unicode)
            _paint(stdscr, frame, footer)

    curses.wrapper(_loop)


# curses colour handling -----------------------------------------------------
_PAIR_IDS: dict[str, int] = {}
_STYLE_DEF = {
    # style -> (fg, bold)
    "title": ("cyan", True),
    "hdr": ("cyan", True),
    "border": ("blue", False),
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
        "yellow": curses.COLOR_YELLOW, "blue": curses.COLOR_BLUE,
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


def _paint_bar(stdscr, row: int, line: Line, max_x: int) -> None:
    """Paint a full-width reverse-video bar (header / footer)."""
    import curses

    x = 0
    for text, style in line:
        if x >= max_x - 1:
            break
        chunk = text[: max(0, max_x - 1 - x)]
        try:
            stdscr.addstr(row, x, chunk, _attr_for(style) | curses.A_REVERSE)
        except curses.error:
            pass
        x += len(chunk)
    if x < max_x - 1:
        try:
            stdscr.addstr(row, x, " " * (max_x - 1 - x),
                          _attr_for("dim") | curses.A_REVERSE)
        except curses.error:
            pass


def _paint(stdscr, frame: Frame, footer: Line | None = None) -> None:
    import curses

    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    body_rows = max_y - 1 if footer is not None else max_y

    for y, line in enumerate(frame):
        if y >= body_rows:
            break
        if y == 0:  # header bar
            _paint_bar(stdscr, y, line, max_x)
            continue
        x = 0
        for text, style in line:
            if x >= max_x - 1:
                break
            chunk = text[: max(0, max_x - 1 - x)]
            try:
                stdscr.addstr(y, x, chunk, _attr_for(style))
            except curses.error:
                pass
            x += len(chunk)

    if footer is not None and max_y >= 2:
        _paint_bar(stdscr, max_y - 1, footer, max_x)
    stdscr.refresh()
