# Configuration

Everything is configured via command-line flags; there is no config file. A few
numerical thresholds are module-level constants you can edit (see
[Tunable constants](#tunable-constants)).

## Command-line flags

Run `python3 -m rbn_tracker --help` for the authoritative list. Current flags:

### Identity & feed

| Flag | Default | Meaning |
|------|---------|---------|
| `--callsign CALL` | `M0TTT` | Callsign used to **log in** to the RBN telnet feed. |
| `--mycall CALL` | `MM1E` | The station tracked in the **Your Station** panel. |

### Windowing & trends

| Flag | Default | Meaning |
|------|---------|---------|
| `--window SECONDS` | `60` | Base sampling/commit window — the "current interval". |
| `--avg-window MINUTES` | `15` | Averaging window for the matrix, recommendation and your-station panels. Displayed magnitudes are totals over this span. |
| `--history N` | `5` | Minimum number of committed windows retained. An hour is always retained regardless, to feed the 60-minute trend horizon. |

### Display

| Flag | Default | Meaning |
|------|---------|---------|
| `--tui` | auto | Force the full-screen viewer. |
| `--no-tui` | off | Force the classic scrolling line report. |
| `--ascii` | off | Force ASCII box-drawing / sparklines / arrows (no Unicode). |
| `--once` | off | Emit a single window then exit (implies the line report). |
| `-v`, `--verbose` | off | Debug logging to stderr. |
| `--version` | – | Print the version and exit. |

The viewer is the default when stdout is an interactive terminal; otherwise (or
with `--once` / `--replay`) the line report is used.

### Contest category

| Flag | Default | Meaning |
|------|---------|---------|
| `--category CAT` | `single` | `single` (Single-Op / Multi-Single), `m2` (Multi-Two), or `mm` (Multi-Multi). Aliases such as `so`, `multi-two`, `m/m` are accepted. Tunes the run/band-change logic — see [usage.md](usage.md#contest-categories). |

### Opponents

| Flag | Default | Meaning |
|------|---------|---------|
| `--opponents MODE` | `off` | `off`, `auto` (contestonlinescore.com) or `manual`. |
| `--opponents-file FILE` | – | Competitor list for `manual` mode. |
| `--opponents-window N` | `5` | Show ±N stations around you. |
| `--contest ID` | – | Contest id for `auto`. |
| `--score-url URL` | – | Override the live-score **JSON** endpoint for `auto`. |
| `--score-api-key KEY` | – | contestonlinescore.com API key for authenticated `auto` (or set the `COS_API_KEY` environment variable). |

### Output & filtering

| Flag | Default | Meaning |
|------|---------|---------|
| `--csv FILE` | – | Append per-window, per-cell stats to CSV (see [below](#csv-output)). |
| `--min-snr DB` | – | Ignore spots weaker than this SNR. |
| `--replay FILE` | – | Replay raw spot lines from a file instead of connecting (see [Replay format](#replay-file-format)). |

## Opponents

The panel is **off by default**. Two sources:

### `manual` (works today)

A plain-text file, one competitor per line: `callsign[, qsos, mults, score]`,
with `#` comments allowed. Include your own call and score so the list can rank
±N around you. Run frequencies are still cross-referenced live from RBN. A
sample is in [`samples/opponents.txt`](../samples/opponents.txt).

```bash
python3 -m rbn_tracker --mycall MM1E \
  --opponents manual --opponents-file samples/opponents.txt
```

### `auto` (incomplete — see limitations)

Targets [contestonlinescore.com](https://contestonlinescore.com). Its data API
is gated behind a key (request from `admin@contestonlinescore.com`); pass it via
`--score-api-key` or `COS_API_KEY`. The authenticate → session → scores flow is
implemented and the JSON parser is deliberately tolerant of field names, but it
has **not been verified against the live API**, so treat it as experimental. If
you point `--score-url` at the human scoreboard *page* (HTML) instead of a JSON
endpoint, the tool detects this and tells you. See
[roadmap.md](roadmap.md#known-limitations).

## Reach, not raw counts

The recommendation does **not** rank by raw spot counts, because a raw count
mixes three things: how many UK stations happen to be calling CQ on a band, how
well the band propagates, and how many skimmers are listening. Only the middle
one is propagation. Instead it uses **reach fraction**:

> reach%(band → continent) = distinct UK stations heard in that continent ÷
> distinct UK stations active on that band

The denominator is the UK stations heard *anywhere* on the band (in practice the
dense EU skimmers hear nearly every audible UK CW signal). So "15m: 75% reach of
4 active" means three of four active UK stations on 15m are reaching that
continent — a propagation signal independent of how busy the band is.

Three refinements:

- **Confidence** — reach from a tiny active population is noisy, so the score is
  weighted by `n / (n + REACH_CONF_K)`.
- **EWMA smoothing** — per-window reach is exponentially smoothed
  (`REACH_EWMA_ALPHA`) so the headline doesn't jitter.
- **Coverage** — a live per-continent skimmer census boosts continents with thin
  coverage (a detection where few are listening means more), bounded by
  `COVERAGE_BOOST_CAP` and referenced to `COVERAGE_REF_SKIMMERS`. Shown as
  `cov~N`.

## Tunable constants

These live at the top of [`rbn_tracker/processing.py`](../rbn_tracker/processing.py)
and can be edited if you want to retune behaviour:

| Constant | Purpose |
|----------|---------|
| `RISE_FACTOR`, `FADE_FACTOR` | Ratio thresholds for RISING / FADING. |
| `RISE_MIN_STREAK` | Consecutive increasing windows required for RISING. |
| `NEAR_ZERO_SPOTTERS`, `MEANINGFUL_SPOTTERS`, `GONE_FLOOR` | Boundaries for NEW / GONE classification. |
| `TREND_HORIZONS` | The set of trend horizons (label, seconds). |
| `REACH_CONF_K` | Confidence half-saturation for reach. |
| `REACH_EWMA_ALPHA` | Smoothing factor for reach (0–1). |
| `COVERAGE_REF_SKIMMERS`, `COVERAGE_BOOST_CAP` | Skimmer-coverage normalisation. |

The recommendation's per-trend weighting (`TREND_WEIGHT`) lives at the top of
[`rbn_tracker/analysis.py`](../rbn_tracker/analysis.py). Band edges are in
[`rbn_tracker/bands.py`](../rbn_tracker/bands.py); the prefix→continent table is
in [`rbn_tracker/continents.py`](../rbn_tracker/continents.py) and is designed to
be extended.

> These are internal constants, not a stable interface — they may be renamed or
> replaced before 1.0.0.

## CSV output

With `--csv FILE`, one row is written per (band × continent) cell per window,
plus rows for the tracked station. Columns:

```
utc_time, window_secs, section, band, continent,
spots, distinct_uk, distinct_spotters, median_snr,
reach_pct, active_uk, coverage,
trend_now, trend_10min, trend_30min, trend_60min
```

- `section` is `cohort` (UK/IE probe) or `mm` (your tracked station).
- `reach_pct` / `active_uk` are populated for `cohort` rows.
- `coverage` is the active-skimmer count for the continent.
- The file is opened in append mode and flushed after every window; a header is
  written when the file is new.

## Replay file format

`--replay FILE` reads one spot per line in the standard RBN/DX-cluster format,
e.g.:

```
DX de DL8TG-#:     14036.0  G4ABC          CW    12 dB  28 wpm  CQ      1234Z
```

A line may be prefixed with `@<offset_secs>\t` to set its receive time so
windows roll realistically; otherwise receive times auto-increment. Regenerate
the bundled synthetic sample with:

```bash
python3 samples/generate_sample.py > samples/sample_feed.txt
```
