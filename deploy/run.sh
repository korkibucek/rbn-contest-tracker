#!/usr/bin/env bash
#
# run.sh — launch the RBN Contest Tracker from its virtualenv.
# Any arguments are passed straight through to `python -m rbn_tracker`.
#
#   ./deploy/run.sh --callsign M0TTT --mycall M0TTT          # live feed (use your call)
#   ./deploy/run.sh --callsign M0TTT --mycall M0TTT --csv contest.csv
#   ./deploy/run.sh --replay samples/sample_feed.txt --mycall MM1E --ascii
#   ./deploy/run.sh --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Virtualenv not found. Run ./deploy/install_macos.sh first." >&2
  exit 1
fi

cd "$REPO_ROOT"
exec "$VENV_PY" -m rbn_tracker "$@"
