#!/bin/sh
# One-time Mac setup; rerun after updating the plugin. Everything lands in
# ~/.cache/feedready, so the installed skill folder stays code-only. Downloads: Python packages (~90 MB from PyPI);
# with --segformer also the 4.4 MB SegFormer-B0 scene model from HuggingFace;
# with --models also EdgeTAM object masks (41 MB) and the MI-GAN heal model (28 MB).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE="$HOME/.cache/feedready"
SEGFORMER=0
MODELS=0
for arg in "$@"; do
  case "$arg" in
    --segformer) SEGFORMER=1 ;;
    --models) MODELS=1 ;;
    *) echo "usage: setup.sh [--segformer] [--models]" >&2; exit 2 ;;
  esac
done
mkdir -p "$CACHE/bin" "$CACHE/models"

# Download to a temp name so an interrupted fetch never looks like an installed model.
fetch() {
  curl -sSfL -o "$1.part" "$2"
  mv "$1.part" "$1"
}

VENV="$CACHE/venv"
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null; then
    uv venv --python 3.14 "$VENV"
  else
    python3 -m venv "$VENV"
  fi
fi
if command -v uv >/dev/null; then
  uv pip install -q --python "$VENV/bin/python" -r "$DIR/requirements.txt"
else
  "$VENV/bin/pip" install -q -r "$DIR/requirements.txt"
fi

if [ "$(uname)" = "Darwin" ]; then
  swiftc -O "$DIR/swift/feedready_engine.swift" -o "$CACHE/bin/feedready-engine"
  shasum -a 256 "$DIR/swift/feedready_engine.swift" | cut -d" " -f1 > "$CACHE/bin/feedready-engine.sha256"
fi

if [ "$SEGFORMER" = 1 ]; then
  BASE=https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512/resolve/main
  fetch "$CACHE/models/segformer_b0_ade_q.onnx" "$BASE/onnx/model_quantized.onnx"
  fetch "$CACHE/models/segformer_config.json" "$BASE/config.json"
fi

if [ "$MODELS" = 1 ]; then
  mkdir -p "$CACHE/models/edgetam"
  BASE=https://huggingface.co/onnx-community/EdgeTAM-ONNX/resolve/main/onnx
  for f in vision_encoder.onnx vision_encoder.onnx_data prompt_encoder_mask_decoder.onnx prompt_encoder_mask_decoder.onnx_data; do
    fetch "$CACHE/models/edgetam/$f" "$BASE/$f"
  done
  fetch "$CACHE/models/migan_pipeline_v2.onnx" https://huggingface.co/andraniksargsyan/migan/resolve/main/migan_pipeline_v2.onnx
fi

"$DIR/run.sh" doctor
