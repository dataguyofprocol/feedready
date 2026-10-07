#!/bin/sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HOME/Desktop/feedready.zip}"
rm -f "$OUT"
cd "$ROOT/skills"
zip -qr "$OUT" feedready -x 'feedready/swift/*' 'feedready/setup.sh' '*/__pycache__/*' '*.DS_Store'
echo "$OUT"
