# RBN Contest Tracker

A Python CLI that connects to the [Reverse Beacon Network](https://www.reversebeacon.net/)
telnet aggregator and prints a **once-per-minute propagation / band-recommendation
report** based on where UK & Ireland CW stations are being heard — with
cross-window **trend tracking** and a dedicated section for your own station
(default **MM1E**).

It answers, mid-contest, between runs: *which band should I be on to work DX
right now, and is my own signal getting out?*

## Quick start

```bash
# Live: connect to RBN, log in as M0TTT, report every 60s, track MM1E
python3 -m rbn_tracker

# Custom login + tracked station + CSV logging
python3 -m rbn_tracker --callsign M0TTT --mycall MM1E --csv contest.csv

# Replay a captured/synthetic feed (no network needed) — great for testing
python3 -m rbn_tracker --replay samples/sample_feed.txt --ascii
```

No third-party packages are required (standard library only). `rich` is
optional and the output degrades gracefully without it; Unicode sparklines fall
back to ASCII automatically (or force it with `--ascii`).

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
| `--window SECONDS` | `60` | Window length |
| `--history N` | `5` | Number of windows kept for trend analysis |
| `--csv FILE` | – | Append per-window, per-cell stats to a CSV |
| `--min-snr DB` | – | Ignore spots weaker than this |
| `--once` | off | Emit a single window then exit (testing) |
| `--replay FILE` | – | Replay raw spot lines instead of connecting |
| `--ascii` | off | Force ASCII sparklines/arrows |
| `-v/--verbose` | off | Debug logging |

`Ctrl-C` shuts down cleanly and flushes any pending CSV writes.

## What the report contains

1. **Header** — UTC time, total spots, total UK/IE spots, tracked call.
2. **Band × continent matrix** — rows are active bands, columns are
   `NA SA EU AF AS OC`. Each cell shows `spots(distinct-spotters)`, and each row
   carries a sparkline + `prev→now` + trend label.
3. **Band recommendation** — bands ranked for working DX (activity into non-EU
   continents), **trend-weighted** so a *rising* band outranks a higher-count
   but *fading* one. Top overall band, best band per open continent (with a
   one-line justification), and which continents look closed.
4. **Your station (MM1E)** — bands you were spotted on, distinct spotters per
   band, continents reached, best/median SNR, CW speed, and the same trend
   logic across windows. If you weren't spotted it says so plainly. If you're
   on a different band than the data recommends, it prints a **QSY suggestion**.
5. **Footer caveat** — RBN coverage is dense in NA/EU and thin in AF/SA/OC, so
   lean on trends and distinct-spotter counts, not absolute numbers.

## Trends

Trends are computed on the **distinct-spotter** series for a band (less noisy
than raw spot counts) over the last `--history` windows. Each active band is
classified `RISING / STEADY / FADING / NEW / GONE`. All thresholds are constants
at the top of [`rbn_tracker/processing.py`](rbn_tracker/processing.py).

## Module layout

| Module | Responsibility |
|--------|----------------|
| `rbn_tracker/callsign.py` | Callsign splitting + UK/IE prefix matching |
| `rbn_tracker/continents.py` | Prefix → continent table (extensible) |
| `rbn_tracker/bands.py` | Frequency (kHz) → band mapping |
| `rbn_tracker/spots.py` | Spot-line parsing |
| `rbn_tracker/processing.py` | Windowing, aggregation, trend logic |
| `rbn_tracker/report.py` | Report rendering, recommendation, MM1E section |
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
