"""Opponent / live-scoreboard interface.

Two ways to get the competitor list:

* **auto** (default) -- pull the live scoreboard for your category from
  contestonlinescore.com, find your station, and take the +/-5 stations around
  you. Your own QSOs/Mults/Score come from the scoreboard too.
* **manual** -- read a config file listing competitor callsigns (optionally with
  their QSOs/Mults/Score). Handy when you know exactly who you're racing, or
  when the scoreboard isn't reachable.

Either way, each opponent's **current run frequency** is cross-referenced from
the live RBN spot stream: RBN spots stations calling CQ, so if a rival is
running we see exactly where. (A rival doing S&P isn't spotted -- shown as such.)

Network note: the auto adapter targets contestonlinescore.com but the exact
contest/endpoint must be reachable; on any failure it degrades gracefully and
the panel says so. Use --score-url to point at a specific feed, or --opponents
manual.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass, field

from .bands import band_for
from .callsign import base_callsign, same_station

log = logging.getLogger("rbn.opponents")

# How recently a rival must have been spotted to count as "running now".
RUN_FRESH_SECS = 180
# How often the auto source re-fetches the scoreboard.
AUTO_REFRESH_SECS = 60
DEFAULT_SCORE_BASE = "https://contestonlinescore.com"
DEFAULT_WINDOW = 5  # +/-N around your position


# --- category mapping ------------------------------------------------------
# Map a scoreboard "class"/category string to our canonical key. We care about
# the number of run transmitters: single (SO or Multi-Single = 1 TX), m2, mm.
def class_to_category(text: str) -> str | None:
    t = (text or "").upper().replace("_", "-").replace(" ", "")
    if not t:
        return None
    if "TWO" in t or "M/2" in t or "M2" in t:
        return "m2"
    if any(k in t for k in ("MULTI-MULTI", "M/M", "MM", "UNLIMITED", "MULTIUNLIMITED")):
        return "mm"
    if any(k in t for k in ("MULTI-ONE", "MULTI-SINGLE", "M/S", "MS", "MULTIONE")):
        return "single"
    if "ONE" in t:  # bare transmitter count -> one signal
        return "single"
    if t.startswith("SO") or "SINGLE-OP" in t or "SINGLEOP" in t or t.startswith("S"):
        return "single"
    if t.startswith("M"):  # bare "MULTI" with no transmitter count -> treat M/M
        return "mm"
    return None


# --- data model ------------------------------------------------------------
@dataclass
class Opponent:
    call: str
    qsos: int | None = None
    mults: int | None = None
    score: int | None = None
    category: str | None = None


@dataclass
class RunInfo:
    freq_khz: float
    band: str
    recv_time: float

    def age(self, now: float) -> float:
        return now - self.recv_time

    def fresh(self, now: float) -> bool:
        return self.age(now) <= RUN_FRESH_SECS


@dataclass
class LeaderboardEntry:
    call: str
    is_me: bool
    qsos: int | None
    mults: int | None
    score: int | None
    d_qsos: int | None  # vs you (positive = ahead of you)
    d_mults: int | None
    d_score: int | None
    run: RunInfo | None


@dataclass
class OpponentsView:
    enabled: bool = False
    source_label: str = ""
    category_name: str = ""
    window: int = DEFAULT_WINDOW
    entries: list[LeaderboardEntry] = field(default_factory=list)
    message: str = ""  # shown when there's nothing to rank


# --- run-frequency tracker -------------------------------------------------
class RunTracker:
    """Tracks the most recent RBN spot (freq/band/time) for watched callsigns."""

    def __init__(self) -> None:
        self._last: dict[str, RunInfo] = {}
        self._watch: set[str] = set()

    def set_watch(self, calls) -> None:
        self._watch = {base_callsign(c) for c in calls}

    def note(self, spotted_call: str, freq_khz: float, recv_time: float) -> None:
        base = base_callsign(spotted_call)
        if base in self._watch:
            self._last[base] = RunInfo(freq_khz, band_for(freq_khz), recv_time)

    def current(self, call: str, now: float) -> RunInfo | None:
        info = self._last.get(base_callsign(call))
        if info is not None and info.fresh(now):
            return info
        return None


# --- leaderboard -----------------------------------------------------------
def build_leaderboard(opponents: list[Opponent], mycall: str,
                      window: int = DEFAULT_WINDOW) -> list[Opponent]:
    """Sort by score (desc) and return the slice of +/-``window`` around you.

    Stations without a score sort to the bottom. If you aren't in the list, the
    top ``2*window+1`` are returned.
    """
    def key(o: Opponent):
        return (o.score if o.score is not None else -1)

    ranked = sorted(opponents, key=key, reverse=True)
    me_idx = next((i for i, o in enumerate(ranked)
                   if same_station(o.call, mycall) or
                   base_callsign(o.call) == base_callsign(mycall)), None)
    if me_idx is None:
        return ranked[: 2 * window + 1]
    lo = max(0, me_idx - window)
    hi = min(len(ranked), me_idx + window + 1)
    return ranked[lo:hi]


def _delta(theirs: int | None, mine: int | None) -> int | None:
    if theirs is None or mine is None:
        return None
    return theirs - mine


# --- sources ---------------------------------------------------------------
def _to_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _first(d: dict, *keys):
    for k in keys:
        for actual in d:
            if actual.lower() == k:
                return d[actual]
    return None


def parse_score_records(data) -> list[Opponent]:
    """Parse a scoreboard payload into Opponents, tolerant of field names.

    Accepts a list of dicts, or a dict containing such a list under a common
    key (``scores``/``data``/``results``/``rows``).
    """
    if isinstance(data, dict):
        for k in ("scores", "data", "results", "rows", "entries"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            data = [data]
    out: list[Opponent] = []
    for rec in data or []:
        if not isinstance(rec, dict):
            continue
        call = _first(rec, "call", "callsign", "operator", "station")
        if not call:
            continue
        cls = _first(rec, "class", "category", "transmitter", "cat", "overlay")
        out.append(Opponent(
            call=str(call).strip().upper(),
            qsos=_to_int(_first(rec, "qsos", "qso", "qs", "contacts")),
            mults=_to_int(_first(rec, "mults", "mult", "multipliers", "multis")),
            score=_to_int(_first(rec, "score", "points", "total")),
            category=class_to_category(str(cls)) if cls else None,
        ))
    return out


class ManualSource:
    """Reads competitor callsigns (and optional scores) from a config file.

    Format -- one per line, ``#`` comments allowed::

        # call, qsos, mults, score
        MM1E, 1395, 402, 1150200
        G4ABC, 1420, 410, 1200300
        GW9T
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def label(self) -> str:
        return f"manual ({self.path})"

    def fetch(self) -> list[Opponent]:
        out: list[Opponent] = []
        with open(self.path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.replace("\t", ",").split(",")]
                call = parts[0].upper()
                if not call:
                    continue
                qsos = _to_int(parts[1]) if len(parts) > 1 else None
                mults = _to_int(parts[2]) if len(parts) > 2 else None
                score = _to_int(parts[3]) if len(parts) > 3 else None
                out.append(Opponent(call, qsos, mults, score))
        return out


class ContestOnlineScoreSource:
    """Auto source: pull the live scoreboard from contestonlinescore.com.

    ``url`` overrides the endpoint entirely (use --score-url). Otherwise a
    contest id must be supplied. ``fetcher`` is injectable for testing.
    """

    def __init__(self, category: str, mycall: str, url: str | None = None,
                 contest: str | None = None, fetcher=None) -> None:
        self.category = category
        self.mycall = mycall
        self.url = url or self._default_url(contest)
        self.contest = contest
        self._fetch_bytes = fetcher or self._http_get

    def label(self) -> str:
        return "contestonlinescore.com"

    @staticmethod
    def _default_url(contest: str | None) -> str | None:
        if not contest:
            return None
        # Tolerant default; the exact path may need --score-url per contest.
        return f"{DEFAULT_SCORE_BASE}/api/scores?contest={contest}"

    @staticmethod
    def _http_get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={
            "User-Agent": "rbn-contest-tracker/1.0",
            "Accept": "application/json, text/plain, */*",
        })
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read()

    def fetch(self) -> list[Opponent]:
        if not self.url:
            raise RuntimeError(
                "no scoreboard URL -- pass --contest ID or --score-url, "
                "or use --opponents manual")
        raw = self._fetch_bytes(self.url)
        text = raw.decode("utf-8", "replace").lstrip("﻿ \t\r\n")
        # A common mistake: pointing --score-url at the human scoreboard *page*
        # (HTML) instead of the JSON/XHR feed it loads behind the scenes.
        if text[:1] in ("<",) or text[:9].lower().startswith("<!doctype"):
            raise RuntimeError(
                "got an HTML page, not a JSON feed -- point --score-url at the "
                "data/XHR endpoint (browser DevTools -> Network -> Fetch/XHR), "
                "or use --opponents manual")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"response was not JSON ({exc})") from exc
        opponents = parse_score_records(data)
        # Keep my own row plus same-category rivals (rows with no category are
        # kept too, since not every feed labels every station).
        return [o for o in opponents
                if o.category in (None, self.category)
                or same_station(o.call, self.mycall)]


# --- manager ---------------------------------------------------------------
class OpponentsManager:
    """Owns the opponent list, refreshes it, and tracks rivals' run freqs."""

    def __init__(self, source, mycall: str, category_name: str,
                 window: int = DEFAULT_WINDOW, auto: bool = False,
                 refresh_secs: int = AUTO_REFRESH_SECS) -> None:
        self.source = source
        self.mycall = mycall
        self.category_name = category_name
        self.window = window
        self.auto = auto
        self.refresh_secs = refresh_secs
        self.tracker = RunTracker()
        self._opponents: list[Opponent] = []
        self._error = ""
        self._last_fetch = 0.0
        self._fetching = False
        self._lock = threading.Lock()

    def note_spot(self, spot) -> None:
        self.tracker.note(spot.spotted, spot.freq_khz, spot.recv_time)

    def _apply(self, opponents: list[Opponent], error: str) -> None:
        with self._lock:
            if opponents is not None:
                self._opponents = opponents
                self.tracker.set_watch([o.call for o in opponents])
            self._error = error

    def _do_fetch(self) -> None:
        try:
            opps = self.source.fetch()
            self._apply(opps, "")
            log.info("opponents: loaded %d stations from %s",
                     len(opps), self.source.label())
        except Exception as exc:  # never let a fetch break the app
            self._apply(None, f"{self.source.label()} unavailable: {exc}")
            log.warning("opponents fetch failed: %s", exc)
        finally:
            self._fetching = False

    def refresh(self, now: float, force: bool = False) -> None:
        """Refresh the list if due. Auto fetches in a background thread."""
        if not force and (now - self._last_fetch) < self.refresh_secs \
                and self._opponents:
            return
        if self._fetching:
            return
        self._last_fetch = now
        if self.auto:
            self._fetching = True
            threading.Thread(target=self._do_fetch, daemon=True).start()
        else:
            self._do_fetch()  # manual file read is cheap/synchronous

    def view(self, now: float) -> OpponentsView:
        with self._lock:
            opponents = list(self._opponents)
            error = self._error
        v = OpponentsView(enabled=True, source_label=self.source.label(),
                          category_name=self.category_name, window=self.window)
        if not opponents:
            v.message = error or "waiting for scores..."
            return v
        slice_ = build_leaderboard(opponents, self.mycall, self.window)
        me = next((o for o in opponents
                   if same_station(o.call, self.mycall)
                   or base_callsign(o.call) == base_callsign(self.mycall)), None)
        my_q = me.qsos if me else None
        my_m = me.mults if me else None
        my_s = me.score if me else None
        for o in slice_:
            is_me = (same_station(o.call, self.mycall)
                     or base_callsign(o.call) == base_callsign(self.mycall))
            v.entries.append(LeaderboardEntry(
                call=o.call, is_me=is_me,
                qsos=o.qsos, mults=o.mults, score=o.score,
                d_qsos=None if is_me else _delta(o.qsos, my_q),
                d_mults=None if is_me else _delta(o.mults, my_m),
                d_score=None if is_me else _delta(o.score, my_s),
                run=self.tracker.current(o.call, now),
            ))
        if me is None:
            v.message = (f"your call {self.mycall} not on the scoreboard yet "
                         "(showing top of category)")
        return v
