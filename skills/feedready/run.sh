#!/bin/sh
# Run feedready with the setup.sh venv when present, else the system python (claude.ai tier).
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/.cache/feedready/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$DIR/scripts/feedready.py" "$@"
