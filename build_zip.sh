#!/bin/sh
# Package the skill for upload to claude.ai (Settings > Capabilities > Skills).
# The phone tier needs only numpy + Pillow; the Mac engine, venv and models stay out.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HOME/Desktop/feedready.zip}"
rm -f "$OUT"
cd "$(dirname "$DIR")"
zip -qr "$OUT" feedready -x 'feedready/.git/*' 'feedready/.gitignore' 'feedready/.venv/*' 'feedready/swift/*' 'feedready/setup.sh' \
  'feedready/build_zip.sh' 'feedready/tests/*' '*/__pycache__/*' '*.DS_Store'
echo "$OUT"
