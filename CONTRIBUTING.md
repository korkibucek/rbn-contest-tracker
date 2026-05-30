# Contributing

Thanks for your interest. This is an alpha-stage, single-maintainer project, so
contributions and bug reports are welcome but please keep changes focused.

> Note: no software license has been declared yet (planned before v1.0.0 — see
> [docs/roadmap.md](docs/roadmap.md)). Until one is in place, the licensing of
> contributions is undefined. If that matters to you, open an issue first.

## Reporting issues

Helpful bug reports include:

- what you ran (the exact command line),
- what you expected and what happened,
- the output of `python3 -m rbn_tracker --version` and `python3 --version`,
- any stderr with `-v` / `--verbose`,
- for a parsing/display bug, the offending RBN line or a minimal `--replay`
  file that reproduces it.

Because the live RBN feed isn't reproducible, a `--replay` snippet is the most
useful thing you can attach.

## Development setup

No build step and no third-party dependencies:

```bash
git clone https://github.com/korkibucek/rbn-contest-tracker.git
cd rbn-contest-tracker
python3 -m unittest discover -s tests -t .
```

Python 3.10+ is required. See [docs/development.md](docs/development.md) for the
project layout, data flow and design conventions.

## Pull requests

- **Keep the standard-library-only constraint** — no new runtime dependencies
  without discussion.
- **Add or update tests** for behaviour changes. The suite must pass:
  `python3 -m unittest discover -s tests -t .`
- **Preserve the ASCII fallback.** Any new Unicode glyph needs an ASCII
  alternative gated on `cfg.use_unicode`; the ASCII output must stay pure ASCII
  (there are tests for this).
- **Update docs in the same PR.** Follow the docs checklist in
  [docs/development.md](docs/development.md#keeping-docs-in-step):
  - new/changed flag → `docs/configuration.md`,
  - new/changed behaviour → `docs/usage.md`,
  - new failure mode → `docs/troubleshooting.md`,
  - any user-visible change → an entry under **Unreleased** in
    [CHANGELOG.md](CHANGELOG.md).
- **Don't overstate features.** If something is partial, mark it as such in the
  README *Known limitations* and the roadmap rather than documenting it as done.
- Match the surrounding code style (4-space indent, type hints on new public
  functions, comments that explain *why*). `python3 -m pyflakes rbn_tracker/
  tests/` should be clean if you have pyflakes installed.

## Good first contributions

- Extending the prefix→continent table in `continents.py` (with a test).
- Troubleshooting/usage doc improvements from real-world use.
- The smaller roadmap items in [docs/roadmap.md](docs/roadmap.md).

If you're planning something larger (packaging, the opponents `auto`
integration, CI), please open an issue to coordinate first.
