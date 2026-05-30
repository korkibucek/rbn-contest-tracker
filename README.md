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

- A pinned **header bar** carries the primary status: clock, uptime, connection
  state, averaging window, spot counts and the tracked call (plus `PAUSED`).
- Content sits in titled, **bordered panels** — *Band × Continent*, *Band
  Trends*, *Recommendation*, *Your Station*, and *Opponents* — each with a
  subtitle and aligned columns so the hierarchy is obvious at a glance.
- A pinned **footer bar** holds the trend legend and the keyboard hints.
- **`q`** quit · **`p`** pause/resume the refresh (freezes the data; the layout
  still adapts on resize).
- Panels size to the terminal width (clamped ~44–120 cols) and stay aligned at
  small sizes; it falls back automatically to the classic line report when
  stdout isn't a TTY (piped/redirected), with `--no-tui`, or with
  `--once`/`--replay`. Force it with `--tui`.

No third-party packages are required (standard library only) — the viewer is
built on `curses`. Unicode box-drawing/sparklines/arrows fall back to ASCII
automatically (or force it with `--ascii`).

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
| `--window SECONDS` | `60` | Base sampling/commit window (the "current interval") |
| `--avg-window MINUTES` | `15` | Averaging window for the band matrix, recommendation and your-station sections — magnitudes are totals over this span |
| `--category CAT` | `single` | Contest category for run/band-change tracking: `single`, `m2` (multi-two), `mm` (multi-multi) |
| `--opponents MODE` | `off` | Opponents leaderboard source: `off`, `auto` (contestonlinescore.com, needs `--score-url`/`--contest`), `manual` |
| `--opponents-file FILE` | – | Competitor list for `manual` mode |
| `--score-url URL` | – | Override the live-score JSON endpoint for `auto` |
| `--contest ID` | – | Contest id for the `auto` live-score source |
| `--score-api-key KEY` | – | contestonlinescore.com API key (or `COS_API_KEY` env) for authenticated `auto` mode |
| `--opponents-window N` | `5` | Show ±N stations around you |
| `--history N` | `5` | Minimum windows of history retained (an hour is always kept regardless, for the 60 min horizon) |
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

The band matrix, recommendation and your-station magnitudes are all computed
over the **averaging window** (`--avg-window`, default 15 min) so they don't
jump around on a single noisy 60 s window; the trend arrows show the direction.

1. **Status bar** — UTC clock, uptime, connection state, spots and UK/IE spots
   over the averaging window, tracked call.
2. **Band × continent matrix** — rows are active bands, columns are
   `NA SA EU AF AS OC`. Each cell shows `spots(distinct-spotters)` **totalled
   over the last 15 min**, with the current-interval trend arrow per band.
3. **Band trends** — for each band, a sparkline and the trend at four horizons:
   the **current interval, 10 min, 30 min and 60 min**.
4. **Band recommendation** — bands ranked for working DX by **reach fraction**
   into non-EU continents (see *Reach* below), confidence- and coverage-weighted
   and **trend-weighted** so a *rising* opener outranks a busy-but-fading band.
   Top overall band, best band per open continent (reach%, active UK, coverage),
   and which continents look closed.
5. **Your station (MM1E)** — a **RUN** block (which bands you're running CQ on,
   band-change/S&P detection, category checks — see below), then bands you were
   spotted on over the last 15 min, distinct spotters per band, continents
   reached, best/median SNR, CW speed, and the multi-horizon trend logic. If you
   weren't spotted it says so plainly. If you're running a different band than
   the data recommends, it prints a **QSY suggestion**.
6. **Footer caveat** — RBN coverage is dense in NA/EU and thin in AF/SA/OC, so
   lean on trends and distinct-spotter counts, not absolute numbers.

## Run / band-change detection (your station)

RBN skimmers spot stations that are **calling CQ**, so a spot of your station on
a band means you were *running* there. When you stop being spotted on a band you
had been running, you've almost certainly gone **S&P** (calling others, which
skimmers don't spot) or **changed band**. The Your Station panel shows a **RUN**
block that:

- lists the band(s) you're **running CQ on right now**, with your **current
  frequency** (median of the skimmer reports) — e.g. `running CQ on: 15m @ 21024.0`;
- flags a band you've gone quiet on — `40m: no CQ for ~3m — gone S&P or off`;
- infers band changes — `band change: 40m → 15m (run moved)`;
- checks your effort against the entered **category** (`--category`).

Categories (by number of simultaneously transmitted run signals):

| `--category` | Meaning | Logic |
|--------------|---------|-------|
| `single` | Single-Op / Multi-Single — one signal at a time | Expects one run band; warns if it sees two at once; suggests a QSY when a better DX band is open |
| `m2` | Multi-Two — two transmitters at once | Shows `running N/2 transmitters`; if a transmitter is idle while a DX band is open, says to put a radio there; notes the CQ WW 8 band-changes/hour/TX limit |
| `mm` | Multi-Multi — one signal per band (up to 6 on HF) | Flags open DX bands you aren't running so you can fill them |

## Opponents leaderboard

Shows the **±5 stations around you in your category**, with how close you are on
**QSOs, Mults and Score**, plus each rival's **current run frequency** —
cross-referenced from the live RBN stream (RBN spots stations calling CQ, so if a
rival is running we see exactly where; a rival doing S&P isn't spotted and shows
`(no CQ)`).

```
OPPONENTS (±5, Single / Multi-Single) -- manual (opponents.txt)
  call          QSOs  Mults        Score   vs you             run
  GM4DEF       1,500    420    1,300,000   +100Q +15M +120.0k 7033.3 40m
> MM1E (you)   1,400    405    1,180,000   --                 7032.0 40m
  GW4ZZZ       1,380    400    1,120,000   -20Q -5M -60.0k    14037.1 20m
```

The panel is **off by default** (the live source needs configuration). Turn it
on with `--opponents auto` or `--opponents manual`.

Sources (`--opponents`):

- **`auto`** — pulls the live scoreboard for your category from
  **contestonlinescore.com**; your own totals come from the scoreboard too. Set
  the contest with `--contest ID`, or point at a specific feed with
  `--score-url URL`. On any failure it degrades gracefully and the panel says so.
  The COS data API is gated — request a key from `admin@contestonlinescore.com`
  and pass it with `--score-api-key KEY` (or the `COS_API_KEY` env var); the app
  then authenticates and pulls scores for you. Without a key, `--score-url` must
  point at a reachable JSON feed (not the HTML scoreboard page).
- **`manual`** — `--opponents-file FILE`, one competitor per line:
  `callsign[, qsos, mults, score]` (`#` comments allowed). Include your own call
  with your score so the list can rank around you. Run frequencies still come
  from RBN.
- **`off`** — hide the panel.

`--opponents-window N` controls how many stations to show either side of you
(default 5).

> Note: the auto adapter targets contestonlinescore.com, but the exact
> contest/endpoint must be reachable from where you run it; the parsing,
> leaderboard and run-frequency logic are verified, but you may need
> `--score-url`/`--contest` for your specific contest.

## Reach, not raw counts (activity normalisation)

UK spots are a *probe* for propagation, but a raw count conflates three things:
how many UK stations happen to be calling CQ on a band, how well it propagates,
and how many skimmers are listening. The first swings wildly and has nothing to
do with propagation, so the recommendation ranks bands by **reach fraction**
instead:

> **reach%(band → continent) = distinct UK stations heard in that continent ÷
> distinct UK stations active on that band** (heard anywhere — in practice the
> dense EU skimmers catch almost every audible UK CW signal).

So *"15m: 75% reach of 4 active"* means three of the four UK stations on 15m are
making it into that continent — a clean propagation signal that doesn't care how
busy the band is. A quiet-but-open band can outrank a busy-but-closed one.

Three refinements keep it honest:

- **Confidence** — reach from a tiny active population is noisy, so the score is
  weighted by `n/(n+k)` (more active UK stations → more trustworthy).
- **EWMA smoothing** — reach is exponentially smoothed across windows so the
  headline doesn't jitter window-to-window.
- **Coverage** — a live per-continent **skimmer census** (`cov~N`) compensates
  thin AF/SA/OC coverage: a detection where few are listening counts for more
  (bounded boost), so sparse regions aren't unfairly buried.

All of these are constants at the top of
[`rbn_tracker/processing.py`](rbn_tracker/processing.py)
(`REACH_CONF_K`, `REACH_EWMA_ALPHA`, `COVERAGE_REF_SKIMMERS`,
`COVERAGE_BOOST_CAP`). The band×continent matrix still shows raw counts; the CSV
gains `reach_pct`, `active_uk` and `coverage` columns.

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
| `rbn_tracker/runstate.py` | Run / band-change detection + contest categories |
| `rbn_tracker/opponents.py` | Opponents leaderboard (auto/manual) + run-freq lookup |
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
