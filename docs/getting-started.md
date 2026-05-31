# Getting started

This page covers installing the tool, running it for the first time, and
confirming it works without needing a live connection.

## Requirements

- **Python 3.10 or newer.** The code uses 3.10+ syntax (PEP 604 unions). Check
  with `python3 --version`.
- **Standard library only** — there are no third-party dependencies to install.
- A terminal that supports `curses` (any normal macOS/Linux terminal). The
  viewer uses Unicode box-drawing where available and falls back to ASCII.
- For the live feed: outbound **TCP to `telnet.reversebeacon.net:7000`**.

## Install from source

The project is not published to PyPI yet. Clone the repository and run it
directly — there is no build step:

```bash
git clone https://github.com/korkibucek/rbn-contest-tracker.git
cd rbn-contest-tracker
python3 -m rbn_tracker --help
```

`python3 -m rbn_tracker --version` prints the current version.

### Install with pip / pipx

Installing also adds a `rbn-contest-tracker` console command. There are no
third-party dependencies.

```bash
pip install .                      # from a clone
pip install "git+https://github.com/korkibucek/rbn-contest-tracker.git"  # without cloning
pipx install .                     # isolated, on your PATH (recommended)
```

Then:

```bash
rbn-contest-tracker --callsign M0TTT --mycall M0TTT   # use your own call
```

Once published to PyPI, `pip install rbn-contest-tracker` / `pipx install
rbn-contest-tracker` will work too.

### macOS: isolated virtualenv (recommended)

A virtualenv isn't strictly required (the app is pure standard library), but it
keeps the install isolated from the system / Homebrew / python.org Pythons:

```bash
./deploy/install_macos.sh                 # create .venv and verify via tests
./deploy/install_macos.sh --python /path  # force a specific interpreter
./deploy/run.sh --callsign M0TTT --mycall M0TTT   # launch; args pass through to the CLI
```

`install_macos.sh`:

1. finds a Python 3.10+ interpreter (suggesting `brew install python@3.12` if
   none is new enough),
2. creates `.venv/` in the repo root,
3. runs the unit test suite to confirm the install is sound.

`run.sh` is a thin launcher that execs the venv's Python against
`python -m rbn_tracker`, passing through any arguments.

> The `--with-rich` flag installs the optional `rich` package. It is **not**
> currently used by the application and can be ignored; it remains as a
> placeholder for possible future colour output.

### Other platforms

There is no platform-specific packaging. On Linux, run the module directly as
above (optionally inside your own `python3 -m venv`). Windows is untested; the
viewer needs a `curses`-capable terminal.

## First run without a network

The repository ships a synthetic feed so you can see the full interface offline:

```bash
python3 -m rbn_tracker --replay samples/sample_feed.txt --mycall MM1E --ascii
```

`--replay` reads spot lines from a file instead of connecting, and drives a
simulated clock so the time windows and trends advance realistically. This is
the quickest way to confirm everything is wired up. The sample data is
**synthetic** — shaped to exercise the trends and your-station logic, not real
propagation.

To print a single window and exit (useful in scripts/CI):

```bash
python3 -m rbn_tracker --replay samples/sample_feed.txt --mycall MM1E --once --ascii
```

(`--mycall` is required in every mode; `--callsign` is only needed for a live
connection, so it is omitted for `--replay`.)

## First live run

```bash
python3 -m rbn_tracker --callsign M0TTT --mycall M0TTT   # use your own call
```

- `--callsign` is the call used to **log in** to the RBN feed (any valid-looking
  call works; it identifies your session to the aggregator). **Required** for a
  live connection.
- `--mycall` is the station the **"Your Station"** panel tracks. **Required.**

On connect you'll see log lines on stderr (`connecting…`, `sent login
callsign…`), then the full-screen viewer once the first data arrives. The first
window takes up to `--window` seconds (default 60) to populate.

Press **`q`** to quit or **`p`** to pause. `Ctrl-C` also exits cleanly and
flushes any pending CSV writes.

## Verifying the install

Run the test suite (no network needed):

```bash
python3 -m unittest discover -s tests -t .
```

All tests should pass. If you used `deploy/install_macos.sh`, this already ran
as part of the install.

## Next steps

- [docs/usage.md](usage.md) — what each panel means and how to read it.
- [docs/configuration.md](configuration.md) — every flag and tunable.
- [docs/troubleshooting.md](troubleshooting.md) — if something doesn't work.
