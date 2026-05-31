# Changelog

All notable changes to this project are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/) from 1.0.0 onward.

While in `0.x` (alpha), **any release may change CLI flags, output format or
internal APIs** without a major-version bump.

## [Unreleased]

### Added

- MIT `LICENSE`.
- `pyproject.toml` packaging with a `rbn-contest-tracker` console entry point;
  installable via `pip` / `pipx` (version single-sourced from
  `rbn_tracker.__version__`).
- GitHub Actions CI: test suite on Python 3.10–3.13, `pyflakes` lint, and a
  package-build + entry-point smoke test.
- GitHub Actions release workflow (`publish.yml`): builds and uploads to PyPI on
  a published GitHub Release, guarding that the tag matches `__version__`. Uses
  an encrypted `PYPI_API_TOKEN` secret; no token stored in the repo.
- CLI surface-lock test (`tests/test_cli_surface.py`) pinning every flag's name,
  default, type, choices and required-ness, so the public command-line surface
  can only change deliberately. The CLI is treated as public API under SemVer
  from 1.0.0.

### Changed

- Redesigned the **RECOMMENDATION** panel for readability: a labelled headline
  (`Top DX band` / `Best reach` / `Reach` / `Trend`) separated by a divider from
  a proper fixed-width table with column headings — **Target, Band, Reach,
  Trend, Spots, Med dB, Coverage** — replacing the old single cramped line per
  continent. Columns are width-sized to their data (so they stay aligned as
  numbers grow) and the right-most ones are dropped on narrow terminals;
  continents with no openings are summarised on one `closed` line. Underlying
  recommendation maths is unchanged.
- **CLI (breaking):** `--mycall` is now **required** in all modes, and
  `--callsign` is **required for a live connection** (not needed with
  `--replay`). The previous demo defaults (`M0TTT` / `MM1E`) are removed so the
  tool no longer logs into RBN, or tracks a station, under a placeholder call.
- `--tui` and `--no-tui` are now mutually exclusive (an explicit error instead
  of silent precedence).
- `--opponents auto` is documented and labelled **experimental** in `--help`.

### Fixed

- TUI panels (the RECOMMENDATION box and others) no longer misalign in
  terminals that render ambiguous-width glyphs — box drawing, arrows, sparkline
  blocks — as two columns. The renderer is now display-column-aware and
  auto-detects such terminals; `RBN_AMBIGUOUS_WIDTH=wide|narrow` overrides the
  detection.

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
