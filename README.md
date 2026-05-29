# RBN Contest Tracker

A Python CLI that connects to the [Reverse Beacon Network](https://www.reversebeacon.net/)
telnet aggregator and shows a **live, full-screen propagation / band-recommendation
viewer** (think `top`, for an HF CW contest) based on where UK & Ireland stations
are being heard — with multi-horizon **trend tracking** and a dedicated section
for your own station (default **MM1E**).

It answers, mid-contest, between runs: *which band should I be on to work DX
right now, and is my own signal getting out?*

Covers the **HF contest bands only** — 160 / 80 / 40 / 20 / 15 / 10 m. The WARC
bands (30/17/12 m), 60 m and 6 m are excluded, since contesting doesn't happen
there; spots on those segments are ignored.

## Quick start

```bash
# Live: connect to RBN, log in as M0TTT, track MM1E — opens the full-screen viewer
python3 -m rbn_tracker

# Custom login + tracked station + CSV logging
python3 -m rbn_tracker --callsign M0TTT --mycall MM1E --csv contest.csv

# Classic scrolling line report instead of the viewer
python3 -m rbn_tracker --no-tui

# Replay a captured/synthetic feed (no network needed) — great for testing
python3 -m rbn_tracker --replay samples/sample_feed.txt --ascii
```

### Interactive viewer

When run live in a terminal, the tracker opens a full-screen viewer that
refreshes in place (~1 s) over a rolling window — no scrolling log to chase.

- **`q`** quit · **`p`** pause/resume the refresh so you can read mid-run.
- A status bar shows the clock, uptime, connection state, spots/window and the
  tracked call; panels below show the band×continent matrix, multi-horizon band
  trends, the DX recommendation, and your own station.
- It falls back automatically to the classic line report when stdout isn't a
  TTY (piped/redirected), with `--no-tui`, or with `--once`/`--replay`. Force it
  with `--tui`.

No third-party packages are required (standard library only) — the viewer is
built on `curses`. Unicode sparklines/arrows fall back to ASCII automatically
(or force it with `--ascii`).

### macOS deployment (virtualenv)

A venv isn't strictly required (the app is pure standard library) but it keeps
the install isolated from the system / Homebrew / python.org Pythons:

```bash
./deploy/install_macos.sh              # creates .venv, verifies via unit tests
./deploy/install_macos.sh --with-rich  # also install optional rich
./deploy/run.sh --csv contest.csv      # launch (args pass through to the CLI)
```

`install_macos.sh` finds a Python 3.10+ interpreter (suggesting
`brew install python@3.12` if none is new enough), builds `.venv`, and runs the
test suite to confirm the install. `run.sh` is a thin launcher that execs the
venv's Python against `python -m rbn_tracker`.

## CLI flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--callsign` | `M0TTT` | Callsign used to log in to the RBN feed |
| `--mycall` | `MM1E` | Station tracked in the "me" section |
| `--window SECONDS` | `60` | Window length (the "current interval") |
| `--history N` | `5` | Windows used for the responsive "now"/recommendation trend (an hour of history is always retained for the longer horizons) |
| `--csv FILE` | – | Append per-window, per-cell stats to a CSV |
| `--min-snr DB` | – | Ignore spots weaker than this |
| `--tui` | auto | Force the full-screen interactive viewer |
| `--no-tui` | off | Force the classic scrolling line report |
| `--once` | off | Emit a single window then exit (testing) |
| `--replay FILE` | – | Replay raw spot lines instead of connecting |
| `--ascii` | off | Force ASCII sparklines/arrows |
| `-v/--verbose` | off | Debug logging |

`Ctrl-C` (or `q` in the viewer) shuts down cleanly and flushes pending CSV writes.

## What it shows

1. **Status bar** — UTC clock, uptime, connection state, spots/window, total
   UK/IE spots, tracked call.
2. **Band × continent matrix** — rows are active bands, columns are
   `NA SA EU AF AS OC`. Each cell shows `spots(distinct-spotters)`, with the
   current-interval trend arrow per band.
3. **Band trends** — for each band, a sparkline and the trend at four horizons:
   the **current interval, 10 min, 30 min and 60 min**.
4. **Band recommendation** — bands ranked for working DX (activity into non-EU
   continents), **trend-weighted** so a *rising* band outranks a higher-count
   but *fading* one. Top overall band, best band per open continent (with a
   one-line justification), and which continents look closed.
5. **Your station (MM1E)** — bands you were spotted on, distinct spotters per
   band, continents reached, best/median SNR, CW speed, and the same
   multi-horizon trend logic. If you weren't spotted it says so plainly. If
   you're on a different band than the data recommends, it prints a **QSY
   suggestion**.
6. **Footer caveat** — RBN coverage is dense in NA/EU and thin in AF/SA/OC, so
   lean on trends and distinct-spotter counts, not absolute numbers.

## Trends

Trends are computed on the **distinct-spotter** series for a band (less noisy
than raw spot counts) and classified `RISING / STEADY / FADING / NEW / GONE`.

Each band is reported at four **horizons** — the current interval (window vs the
previous one) plus **10 / 30 / 60 minutes** — so you can tell a one-window blip
from a real, sustained opening. The longer horizons compare the recent half of
that period against the older half; the current interval and the recommendation
use a responsive short window (`--history`). An hour of window history is always
retained for the 60-minute horizon. All thresholds and the horizon set are
constants at the top of [`rbn_tracker/processing.py`](rbn_tracker/processing.py).

## Module layout

| Module | Responsibility |
|--------|----------------|
| `rbn_tracker/callsign.py` | Callsign splitting + UK/IE prefix matching |
| `rbn_tracker/continents.py` | Prefix → continent table (extensible) |
| `rbn_tracker/bands.py` | Frequency (kHz) → HF contest band mapping |
| `rbn_tracker/spots.py` | Spot-line parsing |
| `rbn_tracker/processing.py` | Windowing, aggregation, trend logic |
| `rbn_tracker/analysis.py` | Recommendation/scoring + horizon trends (shared) |
| `rbn_tracker/report.py` | Classic text report rendering |
| `rbn_tracker/tui.py` | Full-screen interactive viewer (curses) |
| `rbn_tracker/feed.py` | Telnet feed (reconnect/backoff) + replay |
| `rbn_tracker/csvout.py` | CSV logging |
| `rbn_tracker/cli.py` | Argument parsing + main loop |

## Callsign / prefix-matching rules

Matching is **structural**, not `startswith` — `M0TTT` is England (M + digit)
while `MM1E` is Scotland (the two-letter `MM` prefix). Supported UK/IE DXCC:
England (`G`, `M`, `2E`), Scotland (`GM`, `MM`, `2M`), Wales (`GW`, `MW`, `2W`),
N. Ireland (`GI`, `MI`, `2I`), Isle of Man (`GD`, `MD`, `2D`), Jersey
(`GJ`, `MJ`, `2J`), Guernsey (`GU`, `MU`, `2U`), Ireland (`EI`, `EJ`).

**Compound calls.** Portable suffixes (`/P`, `/M`, `/QRP`, `/9` …) are stripped
and the base call keeps its identity — `G4ABC/P` is UK. A **prepended prefix**
(`EA8/G4ABC`, `MD/DL1ABC`) means the operator is working away from the base
call's home DXCC, and per spec is treated as **not** the UK cohort — even when
the prepend itself looks UK. This conservatively excludes visitor operations
from the resident-UK cohort probe. See the unit tests for the authoritative
behaviour.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The prefix-matching suite (`tests/test_callsign.py`) covers every case in the
spec: `MM1E, M0TTT, 2E0ABC, GW4XYZ, EI5XYZ, GD1A, GJ2A, EA8/G4ABC (not UK),
G4ABC/P (UK), MD/DL1ABC (not UK), 2M0ZZZ`.

## Replay file format

One spot per line. A line may be prefixed with `@<offset_secs>\t` to set its
receive time (so `--replay` rolls realistic windows); otherwise times
auto-increment. Regenerate the bundled sample with:

```bash
python3 samples/generate_sample.py > samples/sample_feed.txt
```

The bundled `samples/sample_feed.txt` is **synthetic test data**, shaped to
exercise the trend engine and the MM1E section — it is not real propagation.

## Network note

The live feed is raw TCP to `telnet.reversebeacon.net:7000`. Some sandboxed/
proxied environments only allow standard web ports, in which case the live
connection will time out — use `--replay` there, and run live on a host with
outbound access to port 7000.
