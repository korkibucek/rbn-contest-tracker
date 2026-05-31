# Roadmap

The project is in **alpha** (`0.1.0a1`). This page tracks what's solid, what's
rough, and what needs to happen before a public **v1.0.0**.

## Current status

**Working and tested:**

- RBN telnet connection with login handling, auto-reconnect and backoff.
- Spot parsing; UK/IE structural prefix matching; HF-contest-band mapping;
  prefix→continent mapping.
- Time windowing, the 15-minute averaging view, and multi-horizon trend
  classification.
- Reach-based, confidence-/coverage-/trend-weighted band recommendation.
- Your-station tracking: run detection, run frequency, S&P / band-change
  inference, contest-category logic, QSY suggestion.
- Full-screen `curses` viewer (bordered panels, header/footer bars,
  width-adaptive, ASCII fallback) and the plain-text line report.
- CSV logging; file replay; `--once`.
- Opponents leaderboard in **manual** mode, with live run-frequency lookup.

**Rough / experimental:**

- Opponents **auto** mode (contestonlinescore.com) — see limitations below.

## Known limitations

- **Opponents `auto` is unverified.** contestonlinescore.com gates its data API
  behind a key, and the live response shape hasn't been confirmed against the
  real service. The authenticate→scores flow and a tolerant parser exist, but
  this path should be considered experimental. `manual` mode is the supported
  way to use the leaderboard today.
- **CW-only and UK/IE-centric.** The probe cohort is UK/Ireland calls; the
  continent table is continent-level, not per-DXCC accurate.
- **Heuristic run/S&P detection** on a 60 s grid — momentary excursions or
  skimmer gaps can misread.
- **Reach depends on skimmer density**, which is thin in AF/SA/OC. The coverage
  factor compensates, but low absolute counts there remain inherently noisy.
- **Not yet published to PyPI** (installable from source via `pip`/`pipx`);
  Windows untested.

## Toward v1.0.0

Roughly in priority order. Items are intentionally not dated.

### Must-have for 1.0.0

- [x] **License** — MIT (`LICENSE`), referenced from the README.
- [x] **Packaging** — `pyproject.toml` with a `rbn-contest-tracker` console
      entry point; builds an sdist + wheel; installable via `pip`/`pipx`.
- [x] **CI** — GitHub Actions runs the test suite on Python 3.10–3.13, plus a
      pyflakes lint and a package-build smoke test.
- [ ] **Publish to PyPI** so `pip install rbn-contest-tracker` works. The
      release automation is in place (`.github/workflows/publish.yml` uploads on
      a GitHub Release); the remaining step is the first actual publish (add the
      `PYPI_API_TOKEN` secret and cut a release).
- [ ] **Resolve opponents `auto`**: either verify and harden the
      contestonlinescore.com integration against the live API (and document the
      exact response shape), or keep it clearly experimental/opt-in with
      `manual` as the documented default. (Currently kept experimental.)
- [ ] **Stabilise the CLI surface** — review flag names/defaults and commit to
      them, since post-1.0 changes should follow semver.

### Should-have

- [ ] Configurable colour themes and a no-colour mode (beyond `--ascii`).
- [ ] Per-DXCC continent accuracy where it matters; easier table extension.
- [ ] Make tunable constants configurable via flags rather than code edits.
- [ ] Windows verification and notes.

### Nice-to-have / ideas

- [ ] Other probe cohorts (not just UK/IE) selectable by prefix set.
- [ ] RTTY / digital skimmer support.
- [ ] Persisted history / session resume.
- [ ] N1MM+ or logger integration for the operator's own QSO/score data.

## Versioning

The project will follow [Semantic Versioning](https://semver.org/) from 1.0.0
onward. While in `0.x` / alpha, **any release may change flags, output or
internal APIs.** See [development.md](development.md) for the release process and
how the changelog is maintained.
