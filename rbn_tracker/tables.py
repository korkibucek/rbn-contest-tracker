"""Renderer-agnostic table model for the RECOMMENDATION and YOUR STATION
sections.

The curses TUI and the plain-text report (``--no-tui``) must present the same
information model so the two front-ends can never drift apart. This module owns
the single source of truth for those tables:

* the column specs (``REC_COLS`` / ``STATION_COLS``): key, header, alignment and
  drop-priority, defined once and imported by both renderers;
* the per-row *values* as plain strings (``rec_rows`` / ``station_rows``), so the
  exact field formatting is shared rather than reimplemented per front-end.

The TUI wraps these string values in curses styles; the text report renders them
as an aligned ASCII table via :func:`text_table`. Both consume identical rows.
"""

from __future__ import annotations

from .analysis import best_band_per_continent, mm_horizon_trends
from .continents import CONTINENTS

# Column spec: (key, header, align, drop_priority). Higher drop-priority is shed
# first when a curses terminal is too narrow; priority 0 columns are always
# kept. The text report is not width-constrained and keeps every column.
REC_COLS = [
    ("target", "Target", "<", 0),
    ("band", "Band", "<", 0),
    ("reach", "Reach", "<", 0),
    ("trend", "Trend", "<", 1),
    ("spots", "Spots", ">", 2),
    ("snr", "Med dB", ">", 3),
    ("cov", "Coverage", ">", 4),
]

# YOUR STATION "getting out" table (per band x continent you're heard on).
# Band/Target/Spotters are always kept; the rest are shed on narrow terminals.
# Trend is the band's current ("now") trend in your own spots.
STATION_COLS = [
    ("band", "Band", "<", 0),
    ("target", "Target", "<", 0),
    ("spotters", "Spotters", ">", 0),
    ("trend", "Trend", "<", 1),
    ("best", "Best dB", ">", 2),
    ("med", "Med dB", ">", 3),
    ("speed", "Speed", ">", 4),
]


def snr_num(snr: float | None) -> str:
    """SNR as a bare signed number for a 'dB'-headed table column ('+14', '-')."""
    return "-" if snr is None else f"{snr:+.0f}"


def rec_rows(view, history, avg_windows) -> tuple[list[dict], list[str]]:
    """Best band per open DX continent.

    Returns ``(rows, closed)`` where ``rows`` is one value-dict per open
    continent (keyed by :data:`REC_COLS` keys, all values plain strings) and
    ``closed`` is the list of continents with no UK/IE spots heard there.
    """
    rows: list[dict] = []
    closed: list[str] = []
    for cont, best in best_band_per_continent(view, history, avg_windows).items():
        if best is None:
            closed.append(cont)
            continue
        rows.append({
            "target": cont,
            "band": best.band,
            "reach": f"{best.reach * 100:.0f}% of {best.active_uk}",
            "trend": best.trend,
            "spots": str(best.count),
            "snr": snr_num(best.median_snr),
            "cov": f"~{best.coverage}",
        })
    return rows, closed


def station_rows(view, history, window_secs) -> list[dict]:
    """One value-dict per (band, continent) your station is currently heard on,
    keyed by :data:`STATION_COLS` keys (all values plain strings)."""
    rows: list[dict] = []
    for band in view.mm_bands():
        now_trend = mm_horizon_trends(history, band, window_secs)[0][1]
        for cont in CONTINENTS:
            obs = view.mm.get((band, cont))
            if not obs:
                continue
            speed = (f"{obs.typical_speed}wpm"
                     if obs.typical_speed is not None else "-")
            rows.append({
                "band": band,
                "target": cont,
                "spotters": str(obs.distinct_spotters),
                "trend": now_trend,
                "best": snr_num(obs.best_snr),
                "med": snr_num(obs.median_snr),
                "speed": speed,
            })
    return rows


def text_table(columns, rows: list[dict]) -> list[str]:
    """Render ``rows`` as an aligned, pure-ASCII table: a header line plus one
    line per row, columns separated by two spaces.

    Mirrors the TUI's :func:`tui._table` sizing (each column sized to the wider
    of its header and its values) but emits plain strings and keeps every column
    -- the text report is line-oriented and not width-constrained.
    """
    headers = {k: h for (k, h, _a, _p) in columns}

    def width(k):
        return max(len(headers[k]), max((len(r[k]) for r in rows), default=0))

    w = {k: width(k) for (k, *_r) in columns}

    def pad(s, n, align):
        return f"{s:>{n}}" if align == ">" else f"{s:<{n}}"

    def mkrow(get):
        return "  ".join(pad(get(k), w[k], a) for (k, _h, a, _p) in columns)

    out = [mkrow(lambda k: headers[k])]
    out += [mkrow(lambda k, r=r: r[k]) for r in rows]
    return out
