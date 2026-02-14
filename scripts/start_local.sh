#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/local_runtime"
PID_FILE="${RUNTIME_DIR}/docops_api.pid"
LOG_FILE="${RUNTIME_DIR}/docops_api.log"

log() {
  echo "[start-local] $*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[start-local] required command not found: ${cmd}" >&2
    exit 1
  fi
}

append_csv() {
  local current="$1"
  local item="$2"
  if [[ -z "${item}" ]]; then
    echo "${current}"
    return 0
  fi
  case ",${current}," in
    *",${item},"*)
      echo "${current}"
      ;;
    *)
      if [[ -n "${current}" ]]; then
        echo "${current},${item}"
      else
        echo "${item}"
      fi
      ;;
  esac
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
  echo "[start-local] python3/python not found" >&2
  exit 1
}

is_port_busy() {
  local port="$1"
  "${PYTHON_BIN}" - "${port}" <<'PY'
import socket
import sys

port = int(sys.argv[1])
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        result = sock.connect_ex(("127.0.0.1", port))
    finally:
        sock.close()
except PermissionError:
    # Restricted sandboxes may deny socket checks; treat as "unknown/not busy".
    sys.exit(1)
except OSError:
    sys.exit(1)
sys.exit(0 if result == 0 else 1)
PY
}

wait_for_health() {
  local base_url="$1"
  local max_attempts=40
  local attempt

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    if curl -fsS --max-time 2 "${base_url}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

default_ollama_base_url() {
  if [[ -n "${DOCOPS_OLLAMA_BASE_URL:-}" ]]; then
    echo "${DOCOPS_OLLAMA_BASE_URL}"
    return 0
  fi

  if grep -qi microsoft /proc/version 2>/dev/null; then
    local gateway
    gateway="$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')"
    if [[ -n "${gateway}" ]]; then
      echo "http://${gateway}:11434"
      return 0
    fi
  fi

  echo "http://127.0.0.1:11434"
}

require_cmd poetry
require_cmd curl
PYTHON_BIN="$(pick_python)"

mkdir -p "${RUNTIME_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}")"
  if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
    log "DocOps API is already running (pid=${existing_pid})."
    log "log file: ${LOG_FILE}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

DOCOPS_LOCAL_HOST="${DOCOPS_LOCAL_HOST:-0.0.0.0}"
DOCOPS_LOCAL_PORT="${DOCOPS_LOCAL_PORT:-8000}"

if is_port_busy "${DOCOPS_LOCAL_PORT}"; then
  echo "[start-local] port ${DOCOPS_LOCAL_PORT} is already in use. Stop existing service or set DOCOPS_LOCAL_PORT." >&2
  exit 1
fi

export DOCOPS_ENABLE_WEB_CONSOLE="${DOCOPS_ENABLE_WEB_CONSOLE:-1}"
export DOCOPS_ENABLE_META="${DOCOPS_ENABLE_META:-1}"
export DOCOPS_ENABLE_ASSIST="${DOCOPS_ENABLE_ASSIST:-1}"
export DOCOPS_OLLAMA_MODEL="${DOCOPS_OLLAMA_MODEL:-qwen3:8b}"
export DOCOPS_OLLAMA_BASE_URL="$(default_ollama_base_url)"
export DOCOPS_OLLAMA_USE_PROXY="${DOCOPS_OLLAMA_USE_PROXY:-0}"

ollama_host="$(printf '%s' "${DOCOPS_OLLAMA_BASE_URL}" | sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#')"
no_proxy_value="${NO_PROXY:-${no_proxy:-}}"
no_proxy_value="$(append_csv "${no_proxy_value}" "127.0.0.1")"
no_proxy_value="$(append_csv "${no_proxy_value}" "localhost")"
no_proxy_value="$(append_csv "${no_proxy_value}" "::1")"
no_proxy_value="$(append_csv "${no_proxy_value}" "${ollama_host}")"
export NO_PROXY="${no_proxy_value}"
export no_proxy="${no_proxy_value}"

log "Starting DocOps API on ${DOCOPS_LOCAL_HOST}:${DOCOPS_LOCAL_PORT}"
log "DOCOPS_OLLAMA_BASE_URL=${DOCOPS_OLLAMA_BASE_URL}"
log "DOCOPS_OLLAMA_MODEL=${DOCOPS_OLLAMA_MODEL}"
log "DOCOPS_ENABLE_ASSIST=${DOCOPS_ENABLE_ASSIST}"

(
  cd "${ROOT_DIR}"
  nohup poetry run uvicorn apps.api.main:app --host "${DOCOPS_LOCAL_HOST}" --port "${DOCOPS_LOCAL_PORT}" >"${LOG_FILE}" 2>&1 &
  echo $! >"${PID_FILE}"
)

started_pid="$(cat "${PID_FILE}")"
base_url="http://127.0.0.1:${DOCOPS_LOCAL_PORT}"

if [[ "${DOCOPS_SKIP_HEALTH_WAIT:-0}" == "1" ]]; then
  log "Health wait skipped (DOCOPS_SKIP_HEALTH_WAIT=1)"
elif ! wait_for_health "${base_url}"; then
  echo "[start-local] service failed to pass health check. Last logs:" >&2
  tail -n 120 "${LOG_FILE}" >&2 || true
  kill "${started_pid}" >/dev/null 2>&1 || true
  rm -f "${PID_FILE}"
  exit 1
fi

log "Started (pid=${started_pid})"
log "API: ${base_url}"
log "Web Console: ${base_url}/web"
log "Stop command: bash scripts/stop_local.sh"
log "Health check command: bash scripts/check_local.sh"
