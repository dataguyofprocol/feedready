#!/bin/sh
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

fetch() {
  curl -sSfL -o "$1.part" "$2"
  if [ "$(shasum -a 256 "$1.part" | cut -d" " -f1)" != "$3" ]; then
    rm -f "$1.part"
    echo "checksum mismatch for $2" >&2
    exit 1
  fi
  mv "$1.part" "$1"
}

VENV="$CACHE/venv"
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null; then
    uv venv --python 3.14 "$VENV"
  else
    PY=""
    for cand in python3.14 python3; do
      if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 14))'; then
        PY="$cand"
        break
      fi
    done
    if [ -z "$PY" ]; then
      echo "feedready needs Python 3.14. Install uv (brew install uv, or https://docs.astral.sh/uv/) and rerun setup.sh." >&2
      exit 1
    fi
    "$PY" -m venv "$VENV"
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
  BASE=https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512/resolve/d3e5499fa8701ff0453ca940a8dfeae39b2f1504
  fetch "$CACHE/models/segformer_b0_ade_q.onnx" "$BASE/onnx/model_quantized.onnx" 9a98d6daf3d926869ab8cc4c2ed7374a2bc23b889bb7ca3b0915d15e3c4756bb
  fetch "$CACHE/models/segformer_config.json" "$BASE/config.json" 435799652b2b64c3e422dea20fed4c59651dae9f0e291fd885e9e067fee0ce2a
fi

if [ "$MODELS" = 1 ]; then
  mkdir -p "$CACHE/models/edgetam"
  BASE=https://huggingface.co/onnx-community/EdgeTAM-ONNX/resolve/9c77c7bff7fd0f3079585fa17af7f730ddc531ed/onnx
  fetch "$CACHE/models/edgetam/vision_encoder.onnx" "$BASE/vision_encoder.onnx" ed068218eba96760fe02d04ce899c449660ac813a088d80ed7f42c8bb01e7cec
  fetch "$CACHE/models/edgetam/vision_encoder.onnx_data" "$BASE/vision_encoder.onnx_data" 21e75dba7077dfcb53e8c9a6e99977156f2240ff3f1f9cddc43d66aa1ecb528e
  fetch "$CACHE/models/edgetam/prompt_encoder_mask_decoder.onnx" "$BASE/prompt_encoder_mask_decoder.onnx" d3668299ec3edf70fbb139ec642b54bf3d4be453fd1b688a6b5938e0856fe546
  fetch "$CACHE/models/edgetam/prompt_encoder_mask_decoder.onnx_data" "$BASE/prompt_encoder_mask_decoder.onnx_data" dfa2125e30d08d388732f20c18fb63ab0f0f590cd270eb307f0c2b65919d1be8
  fetch "$CACHE/models/migan_pipeline_v2.onnx" https://huggingface.co/andraniksargsyan/migan/resolve/406830d0fa60666da0071c342ad2fbc8f30c5c64/migan_pipeline_v2.onnx 6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b
fi

"$DIR/run.sh" doctor
