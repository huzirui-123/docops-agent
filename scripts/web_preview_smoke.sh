#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${WEB_DIR:-${ROOT_DIR}/apps/web}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-${ROOT_DIR}/artifacts/frontend}"

mkdir -p "${ARTIFACTS_DIR}"

log() {
  echo "[web-preview-smoke] $*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[web-preview-smoke] required command not found: ${cmd}" >&2
    exit 1
  fi
}

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  echo "[web-preview-smoke] python3/python not found" >&2
  exit 1
}

wait_for_index() {
  local url="$1"
  local attempts=20
  local sleep_seconds=0.5
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${sleep_seconds}"
  done
  return 1
}

require_cmd node
require_cmd npm
require_cmd curl
PYTHON_BIN="$(pick_python)"

if [[ ! -d "${WEB_DIR}" ]]; then
  echo "[web-preview-smoke] web directory not found: ${WEB_DIR}" >&2
  exit 1
fi

preview_pid=""
selected_port=""
selected_log=""
selected_url=""

cleanup() {
  if [[ -n "${preview_pid}" ]] && kill -0 "${preview_pid}" >/dev/null 2>&1; then
    kill "${preview_pid}" >/dev/null 2>&1 || true
    wait "${preview_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log "Running npm ci"
(
  cd "${WEB_DIR}"
  npm ci
)

log "Running npm run build"
(
  cd "${WEB_DIR}"
  npm run build
)

for port in $(seq 4173 4189); do
  preview_log="${ARTIFACTS_DIR}/preview_${port}.log"
  rm -f "${preview_log}"

  log "Trying preview on 127.0.0.1:${port}"
  (
    cd "${WEB_DIR}"
    npm run preview -- --host 127.0.0.1 --port "${port}"
  ) >"${preview_log}" 2>&1 &
  preview_pid=$!

  preview_url="http://127.0.0.1:${port}/"
  if wait_for_index "${preview_url}"; then
    selected_port="${port}"
    selected_log="${preview_log}"
    selected_url="${preview_url}"
    break
  fi

  kill "${preview_pid}" >/dev/null 2>&1 || true
  wait "${preview_pid}" >/dev/null 2>&1 || true
  preview_pid=""
done

if [[ -z "${selected_port}" ]]; then
  echo "[web-preview-smoke] failed to start preview on ports 4173-4189" >&2
  if [[ -n "${preview_log:-}" && -f "${preview_log:-}" ]]; then
    echo "[web-preview-smoke] last preview log:" >&2
    tail -n 80 "${preview_log}" >&2 || true
  fi
  exit 1
fi

log "Selected port ${selected_port}"
curl -fsS "${selected_url}" -o "${ARTIFACTS_DIR}/index.html"

grep -F '<div id="root"></div>' "${ARTIFACTS_DIR}/index.html" >/dev/null
grep -F '<script type="module"' "${ARTIFACTS_DIR}/index.html" >/dev/null

bundle_path="$("${PYTHON_BIN}" - "${ARTIFACTS_DIR}/index.html" <<'PY'
import pathlib
import re
import sys

html = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'<script[^>]*type="module"[^>]*src="([^"]+\.js)"', html)
if not match:
    raise SystemExit(1)
print(match.group(1))
PY
)"

if [[ -z "${bundle_path}" ]]; then
  echo "[web-preview-smoke] unable to extract JS bundle path from index.html" >&2
  exit 1
fi

if [[ "${bundle_path}" =~ ^https?:// ]]; then
  bundle_url="${bundle_path}"
elif [[ "${bundle_path}" =~ ^/ ]]; then
  bundle_url="http://127.0.0.1:${selected_port}${bundle_path}"
else
  bundle_url="http://127.0.0.1:${selected_port}/${bundle_path}"
fi

curl -fsS "${bundle_url}" -o "${ARTIFACTS_DIR}/bundle.js"
grep -F "DocOps Web Console" "${ARTIFACTS_DIR}/bundle.js" >/dev/null

if [[ -n "${selected_log}" ]]; then
  cp "${selected_log}" "${ARTIFACTS_DIR}/preview.log"
fi

echo "selected_port=${selected_port}"
echo "WEB PREVIEW SMOKE PASS"
