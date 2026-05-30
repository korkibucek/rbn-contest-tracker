# RBN Contest Tracker

A terminal tool for HF CW contesters that turns the [Reverse Beacon
Network](https://www.reversebeacon.net/) (RBN) spot stream into a live,
full-screen view of **where UK & Ireland stations are being heard right now** —
so you can answer, mid-contest and between runs:

> *Which band should I be on to work DX, and is my own signal getting out?*

It connects to the RBN telnet aggregator, watches which UK/IE stations the
worldwide skimmer network is hearing, and continuously shows a band-by-continent
picture, multi-horizon propagation trends, a reach-based band recommendation, a
section tracking your own station, and an optional opponents leaderboard.

```
┌─ BAND × CONTINENT ─ spots(spotters) · last 15min ─────────────────────────┐
│ band           NA          SA          EU          AF          AS      now │
│ 20m         18(3)           ·      144(4)           ·           ·  → STEADY│
│ 15m         90(5)           ·           ·           ·           ·  ↑ RISING│
└───────────────────────────────────────────────────────────────────────────┘
┌─ RECOMMENDATION ─ work DX · reach over last 15min ────────────────────────┐
│ TOP DX BAND  15m   best reach NA 100% of 5 active   RISING                 │
│   NA  15m  100% of 5    90sp  med +14dB  cov~5  ↑ RISING                    │
└───────────────────────────────────────────────────────────────────────────┘
```

> ### ⚠️ Status: alpha (pre-release, `0.1.0a1`)
>
> The tool is usable and tested, but **pre-1.0**: CLI flags, output format and
> internal APIs may change without notice between versions. The core
> (feed → parse → window → trend → recommendation → display) is stable and
> covered by tests. The **opponents auto source is incomplete** — it needs a
> contestonlinescore.com API key and the exact live response shape has not been
> verified against the live site (see [Known limitations](#known-limitations)).
> Installable via `pip`/`pipx`, but not yet published to PyPI.

## What it does

- **Band × continent matrix** — for each active HF contest band, how many
  UK/IE stations are heard in each continent (NA, SA, EU, AF, AS, OC).
- **Propagation trends** — per band, a sparkline and RISING / STEADY / FADING /
  NEW / GONE classification at four horizons (current interval, 10 / 30 / 60 min).
- **Reach-based recommendation** — ranks bands for working DX by *reach
  fraction* (what share of active UK stations on a band are reaching each
  continent), so a quiet-but-open band can outrank a busy-but-closed one. See
  [docs/configuration.md](docs/configuration.md#reach-not-raw-counts).
- **Your station** — tracks your own callsign: which band(s) you're running CQ
  on and where, current run frequency, who's hearing you, plus S&P / band-change
  detection and a QSY suggestion when the data favours another band.
- **Opponents leaderboard** *(optional)* — the ±5 stations around you in your
  category with QSO/mult/score deltas and each rival's current run frequency,
  cross-referenced live from RBN.

Scope: **HF contest bands only** (160 / 80 / 40 / 20 / 15 / 10 m). WARC bands
(30 / 17 / 12 m), 60 m and 6 m are intentionally excluded. CW-oriented (the RBN
CW skimmer network is what it consumes).

## Requirements

- **Python 3.10+** (standard library only — no third-party packages required).
- A terminal for the full-screen viewer (built on `curses`). Unicode is used
  where available and falls back to ASCII automatically (or force with `--ascii`).
- **Outbound TCP to `telnet.reversebeacon.net:7000`** for the live feed. If
  that port is blocked you can still use `--replay` against a captured file.

## Install

Clone and run in place — there's nothing to build:

```bash
git clone https://github.com/korkibucek/rbn-contest-tracker.git
cd rbn-contest-tracker
python3 -m rbn_tracker --help
```

Or install it (no third-party dependencies), which also provides a
`rbn-contest-tracker` console command:

```bash
pip install .            # from a clone
# or, without cloning:
pip install "git+https://github.com/korkibucek/rbn-contest-tracker.git"
```

> Not yet published to PyPI; `pip install rbn-contest-tracker` will work once it
> is. `pipx install .` is recommended if you want it on your `PATH` in an
> isolated environment.

On macOS, the helper script sets up an isolated virtualenv and verifies the
install by running the test suite:

```bash
./deploy/install_macos.sh     # creates .venv, runs the tests
./deploy/run.sh               # launch (arguments pass through to the CLI)
```

See [docs/getting-started.md](docs/getting-started.md) for details.

## Quick start

```bash
# Live: connect to RBN, log in as M0TTT, track MM1E — opens the full-screen viewer
python3 -m rbn_tracker --mycall MM1E

# Try it with no network, using the bundled synthetic feed
python3 -m rbn_tracker --replay samples/sample_feed.txt --ascii

# Classic scrolling line report instead of the viewer, with CSV logging
python3 -m rbn_tracker --mycall MM1E --no-tui --csv contest.csv
```

In the viewer: **`q`** quits, **`p`** pauses/resumes. Full walk-through in
[docs/usage.md](docs/usage.md).

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/getting-started.md](docs/getting-started.md) | Install, first run, verifying with the sample feed |
| [docs/usage.md](docs/usage.md) | Running live, reading each panel, common workflows |
| [docs/configuration.md](docs/configuration.md) | Every CLI flag, the reach model, tunable constants, CSV format |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Connection, display, opponents, and replay issues |
| [docs/roadmap.md](docs/roadmap.md) | Path to v1.0.0, known limitations |
| [docs/development.md](docs/development.md) | Project layout, tests, release process, docs maintenance |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Known limitations

- **Opponents `auto` mode is incomplete.** It targets
  contestonlinescore.com, which gates its data API behind a key
  (`admin@contestonlinescore.com`). The authenticate→scores flow is implemented
  but **unverified against the live API**, and the response parser is tolerant
  rather than exact. `manual` mode (a local file) works today. Default is `off`.
- **CW only**, and **UK/IE-centric** — the probe cohort is UK/Ireland callsigns;
  the continent table is pragmatic (continent-level, not per-DXCC accurate).
- **Heuristic run/S&P detection** — inferred from RBN CQ spots on a 60 s grid; a
  brief S&P excursion or a skimmer gap can read as "gone quiet".
- **Reach depends on skimmer coverage** — dense in NA/EU, thin in AF/SA/OC. A
  coverage factor compensates, but absolute counts into sparse regions stay low.
- Installable via `pip`, but **not yet published to PyPI**. Developed and tested
  on macOS and Linux; Windows is untested (the viewer needs a `curses`-capable
  terminal).

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Run the tests with:

```bash
python3 -m unittest discover -s tests -t .
```

## License

Released under the [MIT License](LICENSE).

## About RBN

The Reverse Beacon Network is a worldwide network of receivers ("skimmers") that
continuously decode CW/RTTY signals and report what they hear. Because skimmers
report stations **calling CQ**, an RBN spot of a station is good evidence that
the station is *running* (calling CQ) on that frequency — which is what makes the
"who's being heard where" and "are you getting out" questions answerable.
