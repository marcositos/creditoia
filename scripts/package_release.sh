#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_NAME="creditoia_release.zip"
OUT_PATH="${ROOT_DIR}/${OUT_NAME}"

cd "$ROOT_DIR"
rm -f "$OUT_PATH"

zip -r "$OUT_PATH" . \
  -x ".git/*" \
  -x "__pycache__/*" \
  -x "*.pyc" \
  -x "*.pyo" \
  -x "*.zip"

echo "Pacote gerado em: $OUT_PATH"
