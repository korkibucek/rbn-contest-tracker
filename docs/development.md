# Development

How the code is organised, how to test it, and how releases and docs are kept in
step.

## Project layout

```
rbn_tracker/          the package
  __init__.py         version string
  __main__.py         `python -m rbn_tracker` entry point
  cli.py              argument parsing, main loop, reader thread, run modes
  feed.py             RBN telnet feed (reconnect/backoff) + file replay
  spots.py            parse a raw spot line into a Spot
  callsign.py         callsign splitting + UK/IE structural prefix matching
  continents.py       prefix → continent table (extensible)
  bands.py            frequency (kHz) → HF contest band
  processing.py       windowing, aggregation, trend + reach maths, tunables
  analysis.py         recommendation scoring + horizon trends (shared)
  runstate.py         run / band-change / S&P detection + contest categories
  opponents.py        opponents leaderboard (manual + auto) + run-freq lookup
  report.py           plain-text line report rendering
  tui.py              full-screen curses viewer (pure-layout + painter)
deploy/               macOS install + run scripts
docs/                 this documentation
samples/              synthetic replay feed + generator, sample opponents file
tests/                unittest suite
```

### Data flow

```
TelnetFeed/ReplayFeed  →  parse_spot  →  SpotProcessor (windows + history)
        →  analysis (reach, trends, recommendation) + runstate + opponents
        →  report.py (text)  /  tui.py (curses)
```

`SpotProcessor` keeps a rolling buffer and a deque of committed window
summaries. The display layer aggregates the recent windows into a single view
(`aggregate_windows`) and computes reach/trends over the history.

### Design notes

- **Standard library only.** No third-party runtime dependencies; keep it that
  way unless there's a strong reason.
- **Pure layout, separate painter.** `tui.build_frame` / `build_footer` and
  `report.format_report` return data/text with no curses calls, so they can be
  unit-tested via `flatten_frame`. `tui.run_tui` is the only curses code.
- **ASCII fallback is mandatory.** Every Unicode glyph must have an ASCII
  alternative gated on `cfg.use_unicode`; the ASCII output must encode as ASCII.
  There are tests asserting this — keep them passing.
- **Never crash on bad input.** Malformed spot lines are skipped, not fatal.

## Running the tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite is pure standard library and needs no network. Coverage spans
callsign matching, spot parsing, band/continent mapping, windowing and trends,
reach/coverage maths, run-state detection, opponents parsing, and TUI layout
(panel borders, width alignment incl. narrow terminals, ASCII purity).

### Optional checks

`pyflakes` is a quick lint if available:

```bash
python3 -m pyflakes rbn_tracker/ tests/
```

There is no enforced formatter/type-checker yet; match the surrounding style
(4-space indent, type hints on new public functions, concise comments that
explain *why*).

## Verifying TUI changes without a terminal

`build_frame` is testable directly; render it to text with `flatten_frame`. To
exercise the actual `curses` painter in a headless environment, drive it under a
pseudo-terminal (`pty.fork`) with a `stop_check` that returns true after a few
frames — see how the tests/smoke checks do it. Always check both Unicode and
`--ascii` and at least one narrow width.

## Adding to the data tables

- **New continent prefixes:** extend the table in `continents.py` (longest-prefix
  match wins). Add a test case.
- **Band edges:** `bands.py`. The tool is deliberately HF-contest-only; adding
  WARC/6 m would need a wider rationale.
- **Trend/reach tuning:** the constants at the top of `processing.py` (and
  `TREND_WEIGHT` in `analysis.py`). Treat these as internal until 1.0.0.

## Releases

The project will follow [SemVer](https://semver.org/) from 1.0.0. While in
`0.x`, treat every release as potentially breaking.

Continuous integration (GitHub Actions, `.github/workflows/ci.yml`) runs the
test suite on Python 3.10–3.13, a `pyflakes` lint, and a package build +
console-entry-point smoke test on every push to `main` and every PR.

The version is single-sourced from `rbn_tracker/__init__.__version__` and read
dynamically by `pyproject.toml`, so bumping it in one place updates the package.

Publishing to PyPI is automated by `.github/workflows/publish.yml`: when a
GitHub **Release** is published, it builds the sdist + wheel, checks that the
release tag matches `__version__`, and uploads via
`pypa/gh-action-pypi-publish`. Authentication uses an encrypted GitHub Actions
secret named `PYPI_API_TOKEN` (repo **Settings → Secrets and variables →
Actions**); no token is stored in the repository. The job runs in a `pypi`
environment, so you can require a reviewer before any publish.

### Release checklist

1. Ensure `python3 -m unittest discover -s tests -t .` passes (CI does this too).
2. Move the **Unreleased** items in [CHANGELOG.md](../CHANGELOG.md) under a new
   version heading with today's date.
3. Bump `__version__` in `rbn_tracker/__init__.py` to the release version (the
   publish workflow fails if it does not match the tag).
4. Update docs affected by the change (see the docs checklist below).
5. Commit and merge the above to `main`.
6. Optionally build/inspect locally first: `python -m build` (produces `dist/`).
7. Cut a GitHub Release with tag `vX.Y.Z` (matching `__version__`). The publish
   workflow builds and uploads to PyPI automatically.

> **First publish only:** the PyPI project does not exist yet, so the
> `PYPI_API_TOKEN` secret must initially hold an *account-scoped* token. After
> the first successful upload, replace it with a *project-scoped* token for
> `rbn-contest-tracker` (least privilege).


### Keeping docs in step

Documentation drift is the main risk as the CLI evolves. To prevent it:

- **Single sources of truth.** Flags live in `cli.py`; the flag tables in
  `docs/configuration.md` mirror it. When you add/rename/remove a flag, update
  that table (and `usage.md` if the workflow changes) in the *same* commit.
- **Changelog discipline.** Every user-visible change adds a line under
  **Unreleased** in `CHANGELOG.md` in the same PR — keep it short and factual.
- **Status honesty.** If a feature is partial, say so in the README's *Known
  limitations* and in `docs/roadmap.md`; don't document it as finished.
- **Docs checklist per change:**
  - [ ] New/changed flag → `docs/configuration.md` flag table updated.
  - [ ] New/changed behaviour or panel → `docs/usage.md` updated.
  - [ ] New failure mode → `docs/troubleshooting.md` note added.
  - [ ] User-visible change → `CHANGELOG.md` Unreleased entry.
  - [ ] Capability finished/started → README *Known limitations* and
        `docs/roadmap.md` adjusted.

A future CI job (see the roadmap) should at least run the tests; a docs lint
(e.g. flag names in `configuration.md` matching `--help`) would be a welcome
addition.
