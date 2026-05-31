#!/usr/bin/env bash
#
# install_macos.sh — set up the RBN Contest Tracker in an isolated virtualenv
# on macOS, then verify the install by running the unit tests.
#
# The tracker itself only needs the Python standard library, but a venv keeps
# it cleanly separated from the system / Homebrew / python.org Pythons. Pass
# --with-rich to also install the optional `rich` package.
#
# Usage:
#   ./deploy/install_macos.sh [--with-rich] [--python /path/to/python3]
#
# After install, run it with (use your own call for --callsign/--mycall):
#   ./deploy/run.sh --callsign M0TTT --mycall M0TTT
#   ./deploy/run.sh --callsign M0TTT --mycall M0TTT --csv contest.csv
#   ./deploy/run.sh --replay samples/sample_feed.txt --mycall MM1E --ascii
# ...or directly:  .venv/bin/python -m rbn_tracker --help

set -euo pipefail

# --- pretty output ---------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
info()  { printf '%s==>%s %s\n' "$GREEN$BOLD" "$RESET" "$*"; }
warn()  { printf '%s!!%s %s\n'  "$YELLOW$BOLD" "$RESET" "$*"; }
die()   { printf '%sxx%s %s\n'  "$RED$BOLD" "$RESET" "$*" >&2; exit 1; }

# --- locate the repo root (this script lives in <repo>/deploy) -------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
MIN_PY_MINOR=10   # we use 3.10+ syntax (PEP 604 unions, etc.)

# --- parse args ------------------------------------------------------------
WITH_RICH=0
PYTHON_BIN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-rich) WITH_RICH=1; shift ;;
    --python)    PYTHON_BIN="${2:-}"; shift 2 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[[ "$(uname -s)" == "Darwin" ]] || warn "this script targets macOS; continuing anyway on $(uname -s)."

# --- find a suitable python3 ----------------------------------------------
pick_python() {
  if [[ -n "$PYTHON_BIN" ]]; then echo "$PYTHON_BIN"; return; fi
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then echo "$cand"; return; fi
  done
  echo ""
}

PY="$(pick_python)"
[[ -n "$PY" ]] || die "no python3 found. Install one with:  brew install python@3.12   (or from https://www.python.org/downloads/macos/)"

PY_VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MINOR="$("$PY" -c 'import sys; print(sys.version_info[1])')"
PY_MAJOR="$("$PY" -c 'import sys; print(sys.version_info[0])')"
if [[ "$PY_MAJOR" -ne 3 || "$PY_MINOR" -lt "$MIN_PY_MINOR" ]]; then
  die "found $PY (Python $PY_VER) but Python 3.$MIN_PY_MINOR+ is required.
     Install a newer one:  brew install python@3.12"
fi
info "Using $PY (Python $PY_VER)"

# --- (re)create the virtual environment ------------------------------------
if [[ -d "$VENV_DIR" ]]; then
  info "Reusing existing virtualenv at $VENV_DIR"
else
  info "Creating virtualenv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR" || die "failed to create venv (is the 'venv' module available?)"
fi

VENV_PY="$VENV_DIR/bin/python"
[[ -x "$VENV_PY" ]] || die "venv python missing at $VENV_PY"

info "Upgrading pip"
"$VENV_PY" -m pip install --quiet --upgrade pip

if [[ "$WITH_RICH" -eq 1 ]]; then
  info "Installing optional dependency: rich"
  "$VENV_PY" -m pip install --quiet rich
else
  info "No third-party deps required (run with --with-rich to add optional 'rich')"
fi

# --- verify by running the test suite --------------------------------------
info "Running unit tests to verify the install"
( cd "$REPO_ROOT" && "$VENV_PY" -m unittest discover -s tests -t . ) \
  || die "unit tests failed — install is NOT verified"

# --- done ------------------------------------------------------------------
cat <<EOF

${GREEN}${BOLD}Install complete and verified.${RESET}

Run the tracker (use your own call for --callsign/--mycall):
  ${BOLD}./deploy/run.sh --callsign M0TTT --mycall M0TTT${RESET}              live feed
  ${BOLD}./deploy/run.sh --callsign M0TTT --mycall M0TTT --csv contest.csv${RESET}  with CSV logging
  ${BOLD}./deploy/run.sh --replay samples/sample_feed.txt --mycall MM1E${RESET}     offline demo

Or call Python directly:
  ${BOLD}$VENV_PY -m rbn_tracker --help${RESET}

Note: the live feed uses raw TCP to telnet.reversebeacon.net:7000. If your
network blocks non-standard ports the connection will time out — use --replay.
EOF
