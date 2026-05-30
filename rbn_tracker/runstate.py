"""Detecting whether the tracked station is *running* (calling CQ) per band,
and reasoning about band changes vs S&P against the entered contest category.

Key idea: RBN skimmers spot stations that are **calling CQ**. So a spot of the
tracked station on a band means it was *running* there. When the station stops
being spotted on a band it had been running, it has almost certainly either
gone S&P (calling other stations, which skimmers don't spot) or changed band.

Contest categories (by number of simultaneously transmitted "run" signals):

* Single / Multi-Single -- one transmitted signal at a time (one run band).
* Multi-Two (M/2)       -- two transmitters on the air at once. In CQ WW each
                           transmitter is limited to 8 band changes per hour.
* Multi-Multi (M/M)     -- unlimited transmitters but only one signal per band,
                           i.e. up to one run per band (six on HF).

All thresholds are constants at the top so they're easy to tune.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bands import band_sort_key
from .processing import WindowSummary

# How recently the station must have been spotted to count as "running now",
# and how far back we still bother flagging a band it recently ran on.
RUN_FRESH_WINDOWS = 2     # spotted within the last N windows -> running now
RUN_RECENT_WINDOWS = 10   # ran within the last N windows -> still worth noting

# (display name, max simultaneous run transmitters) keyed by canonical category.
CATEGORY_INFO = {
    "single": ("Single / Multi-Single", 1),
    "m2": ("Multi-Two", 2),
    "mm": ("Multi-Multi", 6),  # one run per HF band
}

# Accepted spellings on the command line -> canonical key.
CATEGORY_ALIASES = {
    "single": "single", "so": "single", "s": "single", "1": "single",
    "ms": "single", "multi-single": "single", "multisingle": "single",
    "m2": "m2", "multi-2": "m2", "multi2": "m2", "multitwo": "m2",
    "multi-two": "m2", "2": "m2",
    "mm": "mm", "multi-multi": "mm", "multimulti": "mm", "multi": "mm",
    "multiunlimited": "mm", "mu": "mm", "6": "mm",
}

# CQ WW Multi-Two band-change limit, per transmitter per clock hour.
M2_BAND_CHANGES_PER_HOUR = 8


def normalize_category(text: str) -> str:
    """Map a user-supplied category string to a canonical key (or raise)."""
    key = CATEGORY_ALIASES.get((text or "").strip().lower())
    if key is None:
        valid = "single, m2 (multi-two), mm (multi-multi)"
        raise ValueError(f"unknown category {text!r}; choose one of: {valid}")
    return key


@dataclass
class RunStatus:
    category_key: str
    category_name: str
    max_tx: int
    running_bands: list[str] = field(default_factory=list)       # CQ now
    sp_or_off: list[tuple[str, int]] = field(default_factory=list)  # (band, min ago)
    qsy: list[tuple[str, str]] = field(default_factory=list)      # (from, to)
    band_changes_last_hour: int = 0

    @property
    def running_count(self) -> int:
        return len(self.running_bands)

    @property
    def spare_tx(self) -> int:
        return max(0, self.max_tx - self.running_count)


def _mm_series(windows: list[WindowSummary], band: str) -> list[int]:
    return [w.mm_band_spotters(band) for w in windows]


def _windows_since_active(series: list[int]) -> int | None:
    """How many windows ago the band was last active (0 = newest), or None."""
    for i in range(len(series) - 1, -1, -1):
        if series[i] > 0:
            return (len(series) - 1) - i
    return None


def _run_started_ago(series: list[int]) -> int:
    """How many windows ago the current trailing run streak began."""
    i = len(series) - 1
    while i >= 0 and series[i] > 0:
        i -= 1
    return (len(series) - 1) - (i + 1)


def compute_run_status(summary: WindowSummary, history: list[WindowSummary],
                       window_secs: int, category_key: str) -> RunStatus:
    """Work out which bands the tracked station is running, and flag bands it
    has gone quiet on (S&P or QSY). ``summary`` is the live snapshot, appended
    as the newest sample for responsiveness."""
    name, max_tx = CATEGORY_INFO[category_key]
    windows = list(history) + [summary]
    status = RunStatus(category_key, name, max_tx)

    bands: set[str] = set()
    for w in windows:
        bands.update(b for (b, _c) in w.mm)

    # (band, windows_ago_last_active) for recently-quiet bands
    quiet: list[tuple[str, int]] = []
    # (band, run_started_windows_ago) for runs that began recently
    started_recently: list[tuple[str, int]] = []
    max_idx = len(windows) - 1
    for band in bands:
        series = _mm_series(windows, band)
        ago = _windows_since_active(series)
        if ago is None:
            continue
        if ago < RUN_FRESH_WINDOWS:
            status.running_bands.append(band)
            started = _run_started_ago(series)
            # A run that began recently (and not at the very start of history)
            # is a candidate "to" band for a QSY.
            if 0 < started <= RUN_RECENT_WINDOWS and started < max_idx:
                started_recently.append((band, started))
        elif ago < RUN_RECENT_WINDOWS:
            quiet.append((band, ago))

        # Count run starts (0 -> active transitions) within the last hour.
        for i in range(1, len(series)):
            if series[i] > 0 and series[i - 1] == 0:
                status.band_changes_last_hour += 1

    status.running_bands.sort(key=band_sort_key)

    # QSY inference: a band that went quiet ~when another band's run started is
    # a band change. Pair most-recent quiet with most-recently-started run.
    quiet.sort(key=lambda x: x[1])              # smallest windows-ago first
    started_recently.sort(key=lambda x: x[1])
    paired_from: set[str] = set()
    used_to: set[str] = set()
    for qband, qago in quiet:
        for tband, tago in started_recently:
            if tband in used_to:
                continue
            if abs(qago - tago) <= 2:           # swapped around the same time
                status.qsy.append((qband, tband))
                paired_from.add(qband)
                used_to.add(tband)
                break

    status.sp_or_off = sorted(
        ((b, max(1, round(a * window_secs / 60))) for b, a in quiet
         if b not in paired_from),
        key=lambda x: band_sort_key(x[0]),
    )
    return status


def idle_tx_suggestion(status: RunStatus, open_dx_bands: list[str]) -> str | None:
    """For M/2 and M/M: if a transmitter is idle while a DX band is open and not
    being run, suggest putting a radio there. ``open_dx_bands`` is best-first."""
    if status.max_tx <= 1 or status.spare_tx <= 0:
        return None
    running = set(status.running_bands)
    candidates = [b for b in open_dx_bands if b not in running]
    if not candidates:
        return None
    take = candidates[: status.spare_tx]
    bands = ", ".join(take)
    verb = "is" if len(take) == 1 else "are"
    return (f"{status.spare_tx} transmitter(s) idle -- {bands} {verb} open into "
            "DX and not being run; put a radio there")
