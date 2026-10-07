#!/bin/sh
# Package the skill for upload to claude.ai (Settings > Capabilities > Skills).
# The phone tier needs only numpy + Pillow; the Swift engine, setup and models stay out.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HOME/Desktop/feedready.zip}"
rm -f "$OUT"
cd "$ROOT/skills"
zip -qr "$OUT" feedready -x 'feedready/swift/*' 'feedready/setup.sh' '*/__pycache__/*' '*.DS_Store'
echo "$OUT"
