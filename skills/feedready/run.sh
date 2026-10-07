#!/bin/sh
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/.cache/feedready/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$DIR/scripts/feedready.py" "$@"
