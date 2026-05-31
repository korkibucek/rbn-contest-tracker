"""Shared recommendation / scoring logic used by both the text report and TUI.

Keeping this in one place means the plain-text report and the full-screen viewer
can never drift apart in how they rank bands or pick the QSY suggestion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .bands import band_sort_key
from .processing import (
    COVERAGE_BOOST_CAP,
    COVERAGE_REF_SKIMMERS,
    DX_CONTINENTS,
    FADING,
    GONE,
    NEW,
    REACH_CONF_K,
    REACH_EWMA_ALPHA,
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
            o.freqs += obs.freqs
        for cont, sk in w.skimmers.items():
            view.skimmers.setdefault(cont, set()).update(sk)
    return view


# --- reach-fraction metrics (activity normalisation) -----------------------

def _ewma(series: list[float], alpha: float) -> float | None:
    if not series:
        return None
    s = series[0]
    for x in series[1:]:
        s = alpha * x + (1.0 - alpha) * s
    return s


def per_window_reach(history: list[WindowSummary], band: str,
                     cont: str) -> list[float]:
    """Per-window reach fraction (UK heard in cont / UK active on band).

    Only windows where the band had UK activity contribute (so dead windows
    don't drag the smoothed value, and we never divide by zero).
    """
    out: list[float] = []
    for w in history:
        denom = w.band_active_uk(band)
        if denom <= 0:
            continue
        cell = w.cell(band, cont)
        num = cell.distinct_uk if cell else 0
        out.append(num / denom)
    return out


def smoothed_reach(history: list[WindowSummary], band: str, cont: str,
                   alpha: float = REACH_EWMA_ALPHA) -> float:
    """EWMA-smoothed reach fraction over the window history (0..1)."""
    return _ewma(per_window_reach(history, band, cont), alpha) or 0.0


def activity_confidence(view: WindowSummary, band: str) -> float:
    """Confidence (0..1) in a band's reach numbers from the active-UK sample."""
    n = view.band_active_uk(band)
    return n / (n + REACH_CONF_K) if n > 0 else 0.0


def coverage_factor(view: WindowSummary, cont: str) -> float:
    """Boost (1..CAP) for continents with thin skimmer coverage.

    A detection where few skimmers are listening means more than the same
    detection where hundreds are. Dense continents get factor 1.0 (no change).
    """
    sk = view.skimmer_count(cont)
    if sk <= 0:
        return 1.0
    return min(COVERAGE_BOOST_CAP, max(1.0, COVERAGE_REF_SKIMMERS / sk))


@dataclass
class ContRec:
    band: str
    reach: float          # smoothed reach fraction 0..1
    active_uk: int        # active-UK population on the band (denominator)
    count: int            # raw spot count in this cell (avg-window total)
    spotters: int         # distinct skimmers in this cell
    median_snr: float | None
    coverage: int         # active skimmers in the continent
    trend: str


@dataclass
class BandRec:
    band: str
    score: float
    trend: str
    active_uk: int
    dx_signal: float      # coverage-weighted sum of reach across DX continents
    best_cont: str | None
    best_reach: float


def _band_reach_signal(view: WindowSummary, history: list[WindowSummary],
                       band: str, alpha: float):
    """(dx_signal, best_cont, best_reach) for a band's DX reach."""
    dx_signal = 0.0
    best_cont, best_reach = None, 0.0
    for cont in DX_CONTINENTS:
        sr = smoothed_reach(history, band, cont, alpha)
        if sr <= 0:
            continue
        dx_signal += sr * coverage_factor(view, cont)
        if sr > best_reach:
            best_reach, best_cont = sr, cont
    return dx_signal, best_cont, best_reach


def score_bands(view: WindowSummary, history: list[WindowSummary],
                avg_windows: int, alpha: float = REACH_EWMA_ALPHA):
    """DX-scored bands, best first, ranked by activity-normalised reach.

    Score = coverage-weighted DX reach x activity-confidence x trend-weight, so a
    quiet-but-propagating band can outrank a busy-but-poorly-propagating one.
    Returns a list of :class:`BandRec`.
    """
    scored: list[BandRec] = []
    for band in view.active_bands():
        dx_signal, best_cont, best_reach = _band_reach_signal(
            view, history, band, alpha)
        if dx_signal <= 0:
            continue
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        conf = activity_confidence(view, band)
        score = dx_signal * conf * TREND_WEIGHT.get(trend, 1.0)
        scored.append(BandRec(band, score, trend, view.band_active_uk(band),
                              dx_signal, best_cont, best_reach))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored


def best_band_per_continent(view: WindowSummary,
                            history: list[WindowSummary], avg_windows: int,
                            alpha: float = REACH_EWMA_ALPHA):
    """Map each DX continent -> best :class:`ContRec`, or ``None`` if closed."""
    result: dict[str, ContRec | None] = {}
    for cont in DX_CONTINENTS:
        best = None  # (weighted_value, ContRec)
        for band in view.active_bands():
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            sr = smoothed_reach(history, band, cont, alpha)
            trend = classify_horizon(band_spotter_series(history, band),
                                     avg_windows)
            conf = activity_confidence(view, band)
            val = sr * coverage_factor(view, cont) * conf * \
                TREND_WEIGHT.get(trend, 1.0)
            rec = ContRec(band, sr, view.band_active_uk(band), cell.count,
                          cell.distinct_spotters, cell.median_snr,
                          view.skimmer_count(cont), trend)
            if best is None or val > best[0]:
                best = (val, rec)
        result[cont] = None if best is None else best[1]
    return result


def recommended_dx_band(view: WindowSummary, history: list[WindowSummary],
                        avg_windows: int,
                        alpha: float = REACH_EWMA_ALPHA) -> tuple[str, str, int] | None:
    """(band, continent, reach_pct_int) of the single best DX opportunity."""
    best = None
    for band in view.active_bands():
        trend = classify_horizon(band_spotter_series(history, band), avg_windows)
        wgt = TREND_WEIGHT.get(trend, 1.0)
        conf = activity_confidence(view, band)
        for cont in DX_CONTINENTS:
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            sr = smoothed_reach(history, band, cont, alpha)
            val = sr * coverage_factor(view, cont) * conf * wgt
            if best is None or val > best[0]:
                best = (val, band, cont, round(sr * 100))
    if best is None:
        return None
    return best[1], best[2], best[3]


# ---------------------------------------------------------------------------
# QSY decision quality: an evidence model + tiered, gated advice.
#
# Raw band *ranking* (score_bands / best_band_per_continent) answers "where is
# the reach?". Operator-facing *QSY advice* must answer a harder question: "is
# the evidence good enough, and clearly better than where I am, to be worth
# leaving a run?". A reach of 87% from two spots into a continent with one
# listening skimmer is not. The model below turns the raw cell metrics into a
# 0..1 confidence score (with a human-readable reason), then only escalates to
# an action when confidence AND the margin over the current band clear
# conservative thresholds. Reach percentage alone never triggers a QSY.
# ---------------------------------------------------------------------------

# Tiers of operator-facing advice, in increasing strength.
QSY_NONE = "none"     # not worth interrupting the operator
QSY_WATCH = "watch"   # a possible opening; worth keeping an eye on
QSY_MOVE = "qsy"      # strong evidence, clearly beats the current run


@dataclass(frozen=True)
class QsyThresholds:
    """Tunable evidence gates for QSY advice. Defaults are deliberately
    conservative for live contest use -- better a missed nudge than yanking an
    operator off a good run on thin data. Tweak here (single source of truth)."""

    min_active: int = 3        # active UK/IE stations on the candidate band
    min_spots: int = 6         # absolute spot count in the candidate cell
    min_skimmers: int = 3      # distinct skimmers hearing the candidate
    min_median_snr: float = 6.0  # dB the median spot is judged "solid" at
    min_windows: int = 3       # windows the opening must have persisted over
    margin: float = 0.15       # candidate reach must beat current by this (frac)
    strong_margin: float = 0.25     # extra margin a full QSY needs
    move_confidence: float = 0.60   # confidence needed for a QSY tier
    watch_confidence: float = 0.35  # confidence needed for a WATCH tier
    good_current_reach: float = 0.50      # "your run is already good" threshold
    good_current_extra_margin: float = 0.15  # ...so demand more before moving
    low_bands: tuple = ("160m", "80m", "40m")
    low_band_daytime_factor: float = 0.5  # cautious daytime prior for low bands


QSY_THRESHOLDS = QsyThresholds()


@dataclass
class BandEvidence:
    """Quality of the evidence behind a (band, continent) DX opportunity."""

    band: str
    cont: str
    reach: float
    active_uk: int
    spots: int
    skimmers: int
    median_snr: float | None
    windows: int          # windows this cell has persisted over
    trend: str
    confidence: float     # 0..1 overall evidence quality
    meets_minimums: bool = False  # every hard quality gate satisfied
    reasons: list = field(default_factory=list)


@dataclass
class QsyAdvice:
    """Operator-facing advice: a tier, the supporting evidence and a message."""

    tier: str                       # QSY_NONE / QSY_WATCH / QSY_MOVE
    candidate: BandEvidence | None
    current_band: str | None
    current_reach: float
    message: str                    # "" when tier is QSY_NONE
    reason: str                     # why it was accepted or rejected


def _ramp(x: float, full: float) -> float:
    """0 at x<=0, rising linearly to 1 by x>=full (clamped to 0..1)."""
    if full <= 0:
        return 1.0
    return max(0.0, min(1.0, x / full))


def _snr_score(median_snr: float | None, solid: float) -> float:
    """0 for missing/very weak signals, ~0.5 around ``solid`` dB, 1 when strong.

    Rejects "weak-only" evidence: a cell whose spots are all near the noise
    floor scores ~0 however many there are.
    """
    if median_snr is None:
        return 0.0
    # ramp centred on `solid`, full width +/- ~12 dB
    return max(0.0, min(1.0, (median_snr - (solid - 12)) / 24.0))


def _daylight_strength(utc_hour: int | None) -> float:
    """Crude UK/IE daylight factor: 0 at night, 1 near solar noon (~12 UTC).

    Used only as a *cautious prior*, not a hard rule -- it scales confidence,
    so genuinely strong low-band evidence can still get through.
    """
    if utc_hour is None:
        return 0.0
    x = (utc_hour - 12) / 6.0          # +/-1 at 06:00 / 18:00 UTC
    return max(0.0, min(1.0, 1.0 - x * x))


def _band_window_count(history: list[WindowSummary], band: str,
                       cont: str) -> int:
    """How many committed windows actually had spots in this (band, cont)."""
    n = 0
    for w in history:
        cell = w.cell(band, cont)
        if cell and cell.count > 0:
            n += 1
    return n


def band_evidence(view: WindowSummary, history: list[WindowSummary], band: str,
                  cont: str, avg_windows: int,
                  thresholds: QsyThresholds = QSY_THRESHOLDS,
                  utc_hour: int | None = None,
                  alpha: float = REACH_EWMA_ALPHA) -> BandEvidence:
    """Score the evidence quality (0..1 confidence) for a band/continent."""
    t = thresholds
    cell = view.cell(band, cont)
    reach = smoothed_reach(history, band, cont, alpha)
    active_uk = view.band_active_uk(band)
    spots = cell.count if cell else 0
    skimmers = cell.distinct_spotters if cell else 0
    median_snr = cell.median_snr if cell else None
    windows = _band_window_count(history, band, cont)
    trend = classify_horizon(band_spotter_series(history, band), avg_windows)

    # Smooth sub-scores: meeting a minimum scores ~0.5, comfortably exceeding
    # it approaches 1. Any single weak factor drags the geometric mean down --
    # which is the point: a tiny denominator, a lone skimmer or weak-only spots
    # should each be enough to withhold a confident recommendation.
    sample = _ramp(active_uk, t.min_active * 2)
    volume = _ramp(spots, t.min_spots * 2)
    diversity = _ramp(skimmers, t.min_skimmers * 2)
    persistence = _ramp(windows, t.min_windows * 2)
    signal = _snr_score(median_snr, t.min_median_snr)

    factors = [sample, volume, diversity, signal, persistence]
    product = 1.0
    for f in factors:
        product *= f
    confidence = product ** (1.0 / len(factors)) if product > 0 else 0.0

    # Cautious daytime prior for low bands (D-layer absorption kills 160/80/40
    # DX in daylight). Scales confidence rather than hard-blocking.
    if band in t.low_bands:
        dl = _daylight_strength(utc_hour)
        confidence *= 1.0 - (1.0 - t.low_band_daytime_factor) * dl

    # Hard quality gates: a confident *move* requires EVERY minimum to be met,
    # so no single strong dimension (e.g. high reach) can compensate for a fatal
    # weakness (one skimmer, two stations, near-noise signals, a brief blip).
    # The smooth confidence above is for ranking/display; this is the floor.
    meets_minimums = (
        active_uk >= t.min_active
        and spots >= t.min_spots
        and skimmers >= t.min_skimmers
        and windows >= t.min_windows
        and median_snr is not None
        and median_snr >= t.min_median_snr
    )

    reasons = [
        f"{active_uk} active", f"{spots} spots", f"{skimmers} skimmers",
        f"median {'-' if median_snr is None else round(median_snr)}dB",
        f"{windows}w persistence",
    ]
    return BandEvidence(band, cont, reach, active_uk, spots, skimmers,
                        median_snr, windows, trend, round(confidence, 3),
                        meets_minimums, reasons)


def _current_band_reach(history: list[WindowSummary], band: str | None,
                        alpha: float) -> float:
    """Best smoothed DX reach on the band the operator is currently running."""
    if not band:
        return 0.0
    return max((smoothed_reach(history, band, c, alpha) for c in DX_CONTINENTS),
               default=0.0)


def qsy_advice(view: WindowSummary, history: list[WindowSummary],
               current_band: str | None, avg_windows: int,
               thresholds: QsyThresholds = QSY_THRESHOLDS,
               utc_hour: int | None = None,
               alpha: float = REACH_EWMA_ALPHA) -> QsyAdvice:
    """Decide whether to advise the operator to QSY, and how strongly.

    Separates raw ranking (which band has the reach) from action advice (is the
    evidence good enough, and clearly better than the current run). Returns a
    :class:`QsyAdvice` whose ``tier`` is QSY_NONE / QSY_WATCH / QSY_MOVE.
    """
    t = thresholds
    if utc_hour is None and view.end_time:
        utc_hour = time.gmtime(view.end_time).tm_hour

    cur_reach = _current_band_reach(history, current_band, alpha)

    # Candidate selection is itself evidence-weighted, not reach-ranked: for
    # each DX band/continent we score reach x confidence, so a thin 87%-from-two-
    # spots cell loses to a well-corroborated one. This is what stops the engine
    # nominating 40m off a sliver of data in the first place.
    best = None  # (reach*confidence, BandEvidence)
    for band in view.active_bands():
        if band == current_band:
            continue
        for cont in DX_CONTINENTS:
            cell = view.cell(band, cont)
            if not cell or cell.count == 0:
                continue
            ev = band_evidence(view, history, band, cont, avg_windows,
                               t, utc_hour, alpha)
            value = ev.reach * ev.confidence
            if best is None or value > best[0]:
                best = (value, ev)

    if best is None:
        return QsyAdvice(QSY_NONE, None, current_band, cur_reach, "",
                         "no DX candidate other than the current band")
    ev = best[1]

    if current_band is None:
        return QsyAdvice(QSY_NONE, ev, current_band, cur_reach, "",
                         "not running a single band")

    margin = ev.reach - cur_reach
    required = t.margin
    if cur_reach >= t.good_current_reach:
        required += t.good_current_extra_margin  # current run is already good
    detail = (f"confidence {ev.confidence:.2f}; margin {round(margin * 100)}pp "
              f"(need {round(required * 100)}); " + ", ".join(ev.reasons))

    cand_pct, cur_pct = round(ev.reach * 100), round(cur_reach * 100)
    if (ev.meets_minimums and ev.confidence >= t.move_confidence
            and margin >= max(required, t.strong_margin)):
        msg = (f"QSY: {ev.band} is clearly outperforming your {current_band} "
               f"run into {ev.cont} ({cand_pct}% vs {cur_pct}% reach).")
        return QsyAdvice(QSY_MOVE, ev, current_band, cur_reach, msg, detail)
    if (ev.confidence >= t.watch_confidence and margin >= required
            and ev.trend in (RISING, NEW)):
        msg = (f"Watch {ev.band}: improving {ev.cont} reach, but evidence is "
               f"still building ({ev.spots} spots / {ev.skimmers} skimmers).")
        return QsyAdvice(QSY_WATCH, ev, current_band, cur_reach, msg, detail)
    return QsyAdvice(QSY_NONE, ev, current_band, cur_reach, "", detail)


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

