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
import unicodedata
from dataclasses import dataclass, field

from .analysis import (
    aggregate_windows,
    band_horizon_trends,
    display_bands,
    QSY_MOVE,
    QSY_WATCH,
    qsy_advice,
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
)
from .report import RenderConfig, arrow, sparkline
from .runstate import compute_run_status, idle_tx_suggestion
from .tables import (
    REC_COLS as _REC_COLS,
    STATION_COLS as _STATION_COLS,
    rec_rows,
    station_rows,
)

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


def _fmt_num(n) -> str:
    return "?" if n is None else f"{n:,}"


# Whether the terminal renders East-Asian *Ambiguous*-width characters (which
# include the box-drawing glyphs, arrows, sparkline blocks, middle dot, etc.) as
# two columns instead of one. Most terminals draw them as one; some (commonly
# with a "treat ambiguous-width as double-width" setting) draw them as two,
# which throws off any layout that assumes one cell per character. Default off;
# the curses painter probes the real terminal and sets it (see
# :func:`set_ambiguous_width`), and ``RBN_AMBIGUOUS_WIDTH`` can force it.
_AMBIGUOUS_WIDE = False


def set_ambiguous_width(wide: bool) -> None:
    """Tell the renderer whether ambiguous-width chars occupy two columns."""
    global _AMBIGUOUS_WIDE
    _AMBIGUOUS_WIDE = wide


def char_width(ch: str) -> int:
    """Display width of a single character, in terminal columns (0, 1 or 2)."""
    if unicodedata.combining(ch):
        return 0
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("W", "F"):
        return 2
    if eaw == "A":
        return 2 if _AMBIGUOUS_WIDE else 1
    return 1


def text_width(s: str) -> int:
    """Display width of a string, in terminal columns."""
    return sum(char_width(c) for c in s)


def _seg_len(line: Line) -> int:
    return sum(text_width(t) for t, _ in line)


def _clip(text: str, cols: int) -> tuple[str, int]:
    """Take a prefix of ``text`` fitting in ``cols`` columns; return (prefix, used).

    A trailing wide character that would overflow by one column is dropped, so
    the prefix never exceeds ``cols``.
    """
    out = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > cols:
            break
        out.append(ch)
        used += w
    return "".join(out), used


def _fit(line: Line, target: int) -> Line:
    """Clip/pad a line's segments to exactly ``target`` display columns."""
    out: Line = []
    used = 0
    for text, style in line:
        if used >= target:
            break
        take, w = _clip(text, target - used)
        if take:
            out.append((take, style))
            used += w
    if used < target:
        out.append((" " * (target - used), "normal"))
    return out


def _hfill(ch: str, cols: int, style: str) -> Line:
    """A run of border char ``ch`` spanning exactly ``cols`` columns.

    If ``ch`` is double-width and ``cols`` is odd, the last column is a space so
    the total stays exact.
    """
    cw = char_width(ch) or 1
    n = cols // cw
    rem = cols - n * cw
    segs: Line = [(ch * n, style)]
    if rem:
        segs.append((" " * rem, style))
    return segs


def _pad(s: str, cols: int, align: str = "<") -> str:
    """Pad/clip ``s`` to exactly ``cols`` display columns (column-aware ljust/rjust)."""
    s, used = _clip(s, cols)
    gap = cols - used
    if gap <= 0:
        return s
    return s + " " * gap if align == "<" else " " * gap + s


def _inner_cols(width: int, uc: bool) -> int:
    """Columns available inside a panel body (between the border + 1 space pads)."""
    return width - 2 * char_width("│" if uc else "|") - 2


def _detect_ambiguous_wide(stdscr) -> bool:
    """Probe the real terminal: does it draw an ambiguous-width glyph as 2 cols?

    ``RBN_AMBIGUOUS_WIDTH=wide|narrow`` forces the answer. Otherwise we print a
    box-drawing glyph off-screen and measure how far the cursor advanced.
    """
    import os

    forced = os.environ.get("RBN_AMBIGUOUS_WIDTH", "").strip().lower()
    if forced in ("wide", "double", "2"):
        return True
    if forced in ("narrow", "single", "1"):
        return False

    import curses

    try:
        max_y, max_x = stdscr.getmaxyx()
        if max_x < 3 or max_y < 1:
            return False
        probe_y = max_y - 1
        stdscr.addstr(probe_y, 0, "─")  # EAW=Ambiguous box-drawing glyph
        _, x = stdscr.getyx()
        stdscr.move(probe_y, 0)
        stdscr.clrtoeol()
        return x >= 2
    except curses.error:
        return False


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
    cw = char_width(b["v"])  # 1, or 2 in a wide-ambiguous terminal
    out: list[Line] = []

    # All sizing is in display columns so the box lines up regardless of how the
    # terminal renders ambiguous-width box-drawing glyphs. The interior between
    # the corners must span (width - 2*corner_width) columns; the body sits
    # inside one border + one space on each side.
    target = width - 2 * cw
    inner = _inner_cols(width, uc)
    sub = f" {b['h']} {subtitle} " if subtitle else f"{b['h']}"
    interior: Line = [(f"{b['h']} ", "border")] + list(title) + [(sub, "dim")]
    ilen = _seg_len(interior)
    if ilen < target:
        interior += _hfill(b["h"], target - ilen, "border")
    else:
        interior = _fit(interior, target)
    out.append([(b["tl"], "border")] + interior + [(b["tr"], "border")])

    for line in body:
        out.append([(b["v"] + " ", "border")] + _fit(line, inner)
                   + [(" " + b["v"], "border")])

    out.append([(b["bl"], "border")] + _hfill(b["h"], target, "border")
               + [(b["br"], "border")])
    return out


def _hr(width: int, uc: bool) -> Line:
    """A thin inner divider line for use inside a panel body."""
    return _hfill("┄" if uc else "-", _inner_cols(width, uc), "dim")


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
    inner = _inner_cols(width, uc)
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
                line.append((_pad(dot, col_w, ">"), "dim"))
        nt = band_horizon_trends(history, band, cfg.window_secs)[0][1]
        now_plain = f"{arrow(nt, uc)} {nt}"
        line.append((" " * max(1, now_w - text_width(now_plain)), "dim"))
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
        line: Line = [(f"{band:<5} ", "accent"), (_pad(spark, SPARK_W, "<") + " ", "normal")]
        line += _horizon_segments(trends, uc)
        rows.append(line)
    return rows


def _chip_lines(chips: list[tuple[str, Line]], inner: int) -> list[Line]:
    """Lay out ``label: value`` chips onto as few lines as fit ``inner`` cols.

    Chips flow left-to-right and wrap to a new line when they would overflow, so
    the headline stays readable and stacks cleanly on narrow terminals.
    """
    lines: list[Line] = []
    cur: Line = []
    curw = 0
    for label, value in chips:
        chip: Line = [(f"{label}: ", "dim")] + value
        w = _seg_len(chip)
        if cur and curw + 3 + w > inner:
            lines.append(cur)
            cur, curw = [], 0
        if cur:
            cur.append(("   ", "dim"))
            curw += 3
        cur += chip
        curw += w
    if cur:
        lines.append(cur)
    return lines


def _table(columns, rows: list[dict], inner: int) -> list[Line]:
    """Render a fixed-width table: a heading row plus one row per entry.

    ``columns`` is a list of ``(key, header, align, drop_priority)``; columns
    with priority 0 are always kept, higher priorities are shed first when the
    table would not fit ``inner`` display columns. ``rows`` is a list of dicts
    mapping every column key to a ``(text, style)`` pair. Each column is sized to
    the wider of its heading and its values, so it stays aligned as values grow.
    """
    headers = {k: h for (k, h, _a, _p) in columns}
    cols = list(columns)

    def width(k):
        return max(len(headers[k]), max((len(r[k][0]) for r in rows), default=0))

    def measure(cs):
        w = {k: width(k) for (k, *_r) in cs}
        total = sum(w.values()) + 2 * max(0, len(cs) - 1)
        return total <= inner, w

    ok, w = measure(cols)
    while not ok and any(p > 0 for *_x, p in cols):
        drop = max((c for c in cols if c[3] > 0), key=lambda c: c[3])
        cols.remove(drop)
        ok, w = measure(cols)

    def mkrow(get) -> Line:
        line: Line = []
        for i, (k, _h, align, _p) in enumerate(cols):
            if i:
                line.append(("  ", "dim"))
            text, sty = get(k)
            line.append((_pad(text, w[k], align), sty))
        return line

    out: list[Line] = [mkrow(lambda k: (headers[k], "dim"))]
    for r in rows:
        out.append(mkrow(lambda k, r=r: r[k]))
    return out


def _rec_body(view, history, cfg, scored, span, uc, width) -> list[Line]:
    if not scored:
        d = "—" if uc else "-"
        return [[(f"no DX reach in the last {span} {d} EU-only or thin "
                  "coverage; watch the trends.", "dim")]]
    inner = _inner_cols(width, uc)

    # --- headline: the single best DX band, every field labelled ----------
    top = scored[0]
    bc = top.best_cont or "DX"
    head = _chip_lines([
        ("Top DX band", [(top.band, "good")]),
        ("Best reach", [(bc, "good")]),
        ("Reach", [(f"{top.best_reach * 100:.0f}% of {top.active_uk} active",
                    "normal")]),
        ("Trend", [(top.trend, _trend_style(top.trend))]),
    ], inner)
    rows: list[Line] = list(head)
    rows.append(_hr(width, uc))

    # --- supporting table: best band per continent ------------------------
    # Values come from the shared table model so the text report and TUI can
    # never diverge; the TUI only layers curses styles on top.
    data, closed = rec_rows(view, history, cfg.avg_windows)
    style = {"target": "dim", "band": "accent", "reach": "good",
             "spots": "normal", "snr": "normal", "cov": "normal"}

    if data:
        trows = [
            {k: (r[k], _trend_style(r["trend"]) if k == "trend" else style[k])
             for (k, *_x) in _REC_COLS}
            for r in data
        ]
        rows += _table(_REC_COLS, trows, inner)

    if closed:
        d = "—" if uc else "-"
        rows.append([(f"closed {d} ", "dim"), (", ".join(closed), "fading")])
    return rows


def _station_body(summary, view, history, cfg, scored, span, uc,
                  width) -> list[Line]:
    rows: list[Line] = []
    run_status = compute_run_status(summary, history, cfg.window_secs,
                                    cfg.category_key)
    open_dx_bands = [r.band for r in scored] if scored else []
    inner = _inner_cols(width, uc)
    arrow_to = "→" if uc else "->"
    dash = "—" if uc else "-"

    # --- headline: run status, every field labelled ----------------------
    cq_val: Line = []
    if run_status.running_bands:
        for i, band in enumerate(run_status.running_bands):
            if i:
                cq_val.append((", ", "dim"))
            cq_val.append((band, "good"))
            if band in run_status.frequencies:
                cq_val.append((f" @ {run_status.frequencies[band]:.1f}",
                               "accent"))
    else:
        cq_val.append(("nothing", "warn"))
    cat_val: Line = [(f"{run_status.category_name}, {run_status.max_tx} TX",
                      "normal")]
    rows += _chip_lines([("CQ on", cq_val), ("Category", cat_val)], inner)

    if run_status.max_tx == 1 and run_status.running_count > 1:
        rows.append([(f"  running {run_status.running_count} bands at once "
                      f"(single TX) {dash} band change in progress?", "warn")])
    for frm, to in run_status.qsy:
        rows.append([("  band change  ", "dim"),
                     (f"{frm} {arrow_to} {to}", "new"), ("  (run moved)", "dim")])
    for band, mins in run_status.sp_or_off:
        rows.append([(f"  {band}  ", "dim"),
                     (f"no CQ for ~{mins}m {dash} gone S&P or off this band",
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
        rows.append([(f"not spotted in the last {span} {dash} check you're "
                      "calling CQ / band may be dead where you are.", "warn")])
        return rows

    # --- table: who is hearing you, where, and how well -------------------
    # Shared row values (see tables.station_rows); the TUI adds styles only.
    style = {"band": "accent", "target": "dim", "spotters": "good",
             "best": "normal", "med": "normal", "speed": "normal"}
    trows = [
        {k: (r[k], _trend_style(r["trend"]) if k == "trend" else style[k])
         for (k, *_x) in _STATION_COLS}
        for r in station_rows(view, history, cfg.window_secs)
    ]
    if trows:
        rows += _table(_STATION_COLS, trows, inner)

    # QSY advice is evidence-gated (see analysis.qsy_advice): only a single-band
    # run can be compared, and a move is suggested only when a candidate band has
    # reliable evidence and clearly beats the current run. Lower-confidence
    # openings show as a quieter WATCH note instead of a QSY alert.
    cur = (run_status.running_bands[0]
           if len(run_status.running_bands) == 1 else None)
    advice = qsy_advice(view, history, cur, cfg.avg_windows,
                        context=cfg.contest_context)
    if advice.tier == QSY_MOVE:
        rows.append(_hr(width, uc))
        label = "QSY  " if advice.kind != "unusual" else "QSY? "
        rows.append([(("» " if uc else ">> "), "warn"), (label, "warn"),
                     (advice.message, "normal")])
    elif advice.tier == QSY_WATCH:
        rows.append(_hr(width, uc))
        # A mult/info note is calmer than a building-run watch.
        label = "MULT  " if advice.kind == "mult" else "WATCH  "
        rows.append([(("· " if uc else "- "), "dim"), (label, "accent"),
                     (advice.message, "dim")])
    return rows


def _opponents_body(opponents, uc) -> list[Line]:
    if not opponents.entries:
        return [[(opponents.message or "no opponents", "dim")]]
    rows: list[Line] = [[
        (f"{'':2}{'call':<11}{'QSOs':>7}{'Mult':>6}{'Score':>12}"
         f"  {'vs you':<19} run", "dim")]]
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
    delta_txt = delta_txt[:19]  # never spill into the run column
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
        (f"  {delta_txt:<19} ", delta_style),
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
                    _rec_body(view, history, cfg, scored, span, uc, width),
                    width, uc)
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
        # Adapt the layout to terminals that render ambiguous-width glyphs (box
        # drawing, arrows, sparklines) as two columns, so the boxes line up.
        set_ambiguous_width(cfg.use_unicode and _detect_ambiguous_wide(stdscr))
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
        chunk, w = _clip(text, max_x - 1 - x)
        if not chunk:
            continue
        try:
            stdscr.addstr(row, x, chunk, _attr_for(style) | curses.A_REVERSE)
        except curses.error:
            pass
        x += w
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
            chunk, w = _clip(text, max_x - 1 - x)
            if not chunk:
                continue
            try:
                stdscr.addstr(y, x, chunk, _attr_for(style))
            except curses.error:
                pass
            x += w

    if footer is not None and max_y >= 2:
        _paint_bar(stdscr, max_y - 1, footer, max_x)
    stdscr.refresh()
