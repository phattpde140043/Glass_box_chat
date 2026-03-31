#!/usr/bin/env bash

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT_DIR/apps/web"
WORKSPACE_NAME="glass-box-web"
PNPM_COMMAND=()

if [[ ! -f "$WEB_DIR/package.json" ]]; then
  echo "[run-frontend] Missing package file: $WEB_DIR/package.json" >&2
  exit 1
fi

if command -v pnpm >/dev/null 2>&1; then
  PNPM_COMMAND=(pnpm)
elif command -v corepack >/dev/null 2>&1; then
  PNPM_COMMAND=(corepack pnpm)
  echo "[run-frontend] pnpm not found. Falling back to corepack pnpm."
elif command -v npx >/dev/null 2>&1; then
  PNPM_COMMAND=(npx --yes pnpm)
  echo "[run-frontend] pnpm/corepack not found. Falling back to npx pnpm."
elif command -v npm >/dev/null 2>&1; then
  PNPM_COMMAND=(npm exec --yes pnpm)
  echo "[run-frontend] pnpm/corepack/npx not found. Falling back to npm exec pnpm."
else
  echo "[run-frontend] pnpm, corepack, npx, and npm are not available in PATH." >&2
  exit 1
fi

INSTALL_COMMAND=("${PNPM_COMMAND[@]}" install --frozen-lockfile)
BUILD_COMMAND=("${PNPM_COMMAND[@]}" --filter "$WORKSPACE_NAME" run build)
START_COMMAND=("${PNPM_COMMAND[@]}" --filter "$WORKSPACE_NAME" run start)

if [[ ! -f "$ROOT_DIR/pnpm-lock.yaml" ]]; then
  INSTALL_COMMAND=("${PNPM_COMMAND[@]}" install)
fi

pushd "$ROOT_DIR" >/dev/null || exit 1

echo "[run-frontend] Syncing Node dependencies..."
if ! "${INSTALL_COMMAND[@]}"; then
  EXIT_CODE=$?
  popd >/dev/null || true
  exit "$EXIT_CODE"
fi

echo "[run-frontend] Building latest frontend bundle..."
if ! "${BUILD_COMMAND[@]}"; then
  EXIT_CODE=$?
  popd >/dev/null || true
  exit "$EXIT_CODE"
fi

if [[ "${NO_START:-}" == "1" ]]; then
  echo "[run-frontend] Build completed. Skipping Next.js start because NO_START=1."
  popd >/dev/null || true
  exit 0
fi

echo "[run-frontend] Starting Next.js production server..."
"${START_COMMAND[@]}"
EXIT_CODE=$?

popd >/dev/null || true
exit "$EXIT_CODE"