#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/local_runtime"
PID_FILE="${RUNTIME_DIR}/docops_api.pid"
LOG_FILE="${RUNTIME_DIR}/docops_api.log"

log() {
  echo "[stop-local] $*"
}

stop_pid() {
  local pid="$1"
  local attempts=20
  local i

  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    return 0
  fi

  kill "${pid}" >/dev/null 2>&1 || true
  for ((i = 1; i <= attempts; i++)); do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done

  kill -9 "${pid}" >/dev/null 2>&1 || true
}

if [[ ! -f "${PID_FILE}" ]]; then
  log "No pid file found (${PID_FILE}). Nothing to stop."
  exit 0
fi

pid="$(cat "${PID_FILE}")"
if [[ -z "${pid}" ]]; then
  rm -f "${PID_FILE}"
  log "Empty pid file removed."
  exit 0
fi

if kill -0 "${pid}" >/dev/null 2>&1; then
  log "Stopping DocOps API (pid=${pid})"
  stop_pid "${pid}"
else
  log "Process ${pid} is not running."
fi

rm -f "${PID_FILE}"
log "Stopped."
if [[ -f "${LOG_FILE}" ]]; then
  log "log file: ${LOG_FILE}"
fi
