#!/usr/bin/env bash

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT_DIR/apps/api"
VENV_DIR="$API_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON_BOOTSTRAP=()

select_python_bootstrap() {
  local candidates=(python3.12 python3.11 python3.10 python3 python)
  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BOOTSTRAP=("$candidate")
      return 0
    fi
  done
  return 1
}

if [[ ! -f "$API_DIR/requirements.txt" ]]; then
  echo "[run-backend] Missing requirements file: $API_DIR/requirements.txt" >&2
  exit 1
fi

if ! select_python_bootstrap; then
  echo "[run-backend] Python was not found in PATH." >&2
  exit 1
fi

BOOTSTRAP_VERSION="$(${PYTHON_BOOTSTRAP[@]} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [[ -x "$VENV_PYTHON" ]]; then
  VENV_VERSION="$($VENV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$VENV_VERSION" == "3.13" && "$BOOTSTRAP_VERSION" != "3.13" ]]; then
    echo "[run-backend] Recreating virtual environment with Python $BOOTSTRAP_VERSION for better dependency compatibility..."
    rm -rf "$VENV_DIR"
  fi
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[run-backend] Creating virtual environment with Python $BOOTSTRAP_VERSION..."
  if ! "${PYTHON_BOOTSTRAP[@]}" -m venv "$VENV_DIR"; then
    exit $?
  fi
fi

echo "[run-backend] Syncing Python dependencies..."
if ! "$VENV_PYTHON" -m pip install --upgrade pip; then
  exit $?
fi

export WEATHER_ENABLE_BERT_EXTRACTOR="${WEATHER_ENABLE_BERT_EXTRACTOR:-false}"
export WEATHER_BERT_MODEL="${WEATHER_BERT_MODEL:-dslim/bert-base-NER}"
export WEATHER_BERT_MIN_SCORE="${WEATHER_BERT_MIN_SCORE:-0.5}"

if ! "$VENV_PYTHON" -m pip install -r "$API_DIR/requirements.txt"; then
  exit $?
fi

if [[ "$WEATHER_ENABLE_BERT_EXTRACTOR" == "1" || "$WEATHER_ENABLE_BERT_EXTRACTOR" == "true" || "$WEATHER_ENABLE_BERT_EXTRACTOR" == "yes" || "$WEATHER_ENABLE_BERT_EXTRACTOR" == "on" ]]; then
  echo "[run-backend] Installing optional BERT extractor dependencies..."
  if ! "$VENV_PYTHON" -m pip install -r "$API_DIR/requirements-bert.txt"; then
    exit $?
  fi
fi

if [[ "${NO_START:-}" == "1" ]]; then
  echo "[run-backend] Dependency sync completed. Skipping server start because NO_START=1."
  exit 0
fi

echo "[run-backend] Starting FastAPI with auto-reload..."
pushd "$ROOT_DIR" >/dev/null || exit 1
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
"$VENV_PYTHON" -m uvicorn glass_box_chat.main:app --host 0.0.0.0 --port 8000 --reload
EXIT_CODE=$?
popd >/dev/null || true

exit "$EXIT_CODE"