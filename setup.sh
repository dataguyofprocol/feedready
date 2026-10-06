#!/bin/sh
# One-time Mac setup. Downloads: Python packages (~90 MB from PyPI);
# with --segformer also the 4.4 MB SegFormer-B0 scene model from HuggingFace.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE="$HOME/.cache/feedready"
mkdir -p "$CACHE/bin" "$CACHE/models"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  if command -v uv >/dev/null; then
    uv venv --python 3.14 "$DIR/.venv"
    uv pip install --python "$DIR/.venv/bin/python" -r "$DIR/requirements.txt"
  else
    python3 -m venv "$DIR/.venv"
    "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
  fi
fi

if [ "$(uname)" = "Darwin" ]; then
  swiftc -O "$DIR/swift/feedready_engine.swift" -o "$CACHE/bin/feedready-engine"
fi

if [ "$1" = "--segformer" ]; then
  BASE=https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512/resolve/main
  curl -sSfL -o "$CACHE/models/segformer_b0_ade_q.onnx" "$BASE/onnx/model_quantized.onnx"
  curl -sSfL -o "$CACHE/models/segformer_config.json" "$BASE/config.json"
fi

"$DIR/run.sh" doctor
