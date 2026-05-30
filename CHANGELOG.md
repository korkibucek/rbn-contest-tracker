# Changelog

All notable changes to this project are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/) from 1.0.0 onward.

While in `0.x` (alpha), **any release may change CLI flags, output format or
internal APIs** without a major-version bump.

## [Unreleased]

Nothing yet.

## [0.1.0a1] — alpha

First documented pre-release. Everything below predates formal versioning and is
summarised from development history; treat it as the initial alpha baseline.

### Added

- RBN telnet feed client with login handling, automatic reconnect and
  exponential backoff; file-replay mode (`--replay`) and `--once`.
- Spot parsing and enrichment (band, spotter continent, UK/IE flag).
- Structural UK/IE callsign prefix matching (handles devolved/crown prefixes,
  portable suffixes and prepended prefixes).
- HF-contest-only band mapping (160/80/40/20/15/10 m); non-contest-band spots
  are dropped.
- Extensible callsign-prefix → continent table.
- Time windowing with a configurable averaging window (`--avg-window`, default
  15 min) and multi-horizon trend classification (current / 10 / 30 / 60 min).
- Reach-based band recommendation (reach fraction, confidence weighting, EWMA
  smoothing, and a per-continent skimmer-coverage adjustment) — ranks bands by
  propagation rather than raw activity.
- Your-station tracking: run detection, current run frequency, S&P /
  band-change inference, contest-category logic (`--category single|m2|mm`),
  and a QSY suggestion.
- Opponents leaderboard (`--opponents`): **manual** file source with live
  run-frequency cross-reference from RBN, and an **experimental, unverified**
  contestonlinescore.com `auto` source (off by default).
- Full-screen `curses` viewer with bordered panels, pinned header/footer bars,
  width-adaptive layout, `q`/`p` keys, and a plain-text line report fallback.
- CSV logging (`--csv`) including reach%, active-UK and coverage columns.
- `--version` flag.
- macOS install/run scripts (`deploy/`) and a synthetic sample feed (`samples/`).
- Documentation set: README plus `docs/` (getting-started, usage, configuration,
  troubleshooting, roadmap, development), `CONTRIBUTING.md`, this changelog.

### Known limitations

See [docs/roadmap.md](docs/roadmap.md#known-limitations). In brief: opponents
`auto` is unverified against the live API; CW-only and UK/IE-centric; run/S&P
detection is heuristic; no license is declared yet; not packaged for PyPI.

[Unreleased]: https://github.com/korkibucek/rbn-contest-tracker/compare/main...HEAD
