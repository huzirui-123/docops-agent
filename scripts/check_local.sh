#!/usr/bin/env bash
set -euo pipefail

DOCOPS_LOCAL_PORT="${DOCOPS_LOCAL_PORT:-8000}"
DOCOPS_CHECK_ASSIST="${DOCOPS_CHECK_ASSIST:-1}"
DOCOPS_CHECK_ASSIST_TIMEOUT="${DOCOPS_CHECK_ASSIST_TIMEOUT:-90}"
BASE_URL="${DOCOPS_BASE_URL:-http://127.0.0.1:${DOCOPS_LOCAL_PORT}}"

log() {
  echo "[check-local] $*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[check-local] required command not found: ${cmd}" >&2
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
  echo "[check-local] python3/python not found" >&2
  exit 1
}

require_cmd curl
PYTHON_BIN="$(pick_python)"

log "Checking ${BASE_URL}/healthz"
healthz_json="$(curl -fsS --max-time 5 "${BASE_URL}/healthz")"
"${PYTHON_BIN}" -c '
import json
import sys

obj = json.loads(sys.argv[1])
if obj.get("status") != "ok":
    raise SystemExit("healthz.status != ok")
' "${healthz_json}"

log "Checking ${BASE_URL}/health"
health_json="$(curl -fsS --max-time 5 "${BASE_URL}/health")"
"${PYTHON_BIN}" -c '
import json
import sys

obj = json.loads(sys.argv[1])
if obj.get("ok") is not True:
    raise SystemExit("health.ok != true")
' "${health_json}"

log "Checking ${BASE_URL}/v1/meta"
meta_json="$(curl -fsS --max-time 8 "${BASE_URL}/v1/meta")"
meta_info="$("${PYTHON_BIN}" -c '
import json
import sys

obj = json.loads(sys.argv[1])
skills = obj.get("supported_skills") or []
if not skills:
    raise SystemExit("supported_skills empty")
supports_assist = bool(obj.get("supports_assist"))
print("1" if supports_assist else "0")
print(",".join(skills))
' "${meta_json}")"

supports_assist="$(printf '%s' "${meta_info}" | sed -n '1p')"
skills_csv="$(printf '%s' "${meta_info}" | sed -n '2p')"
log "Meta OK (supported_skills=${skills_csv})"

if [[ "${DOCOPS_CHECK_ASSIST}" != "1" ]]; then
  log "Assist check skipped (DOCOPS_CHECK_ASSIST=${DOCOPS_CHECK_ASSIST})"
  echo "LOCAL CHECK PASS"
  exit 0
fi

if [[ "${supports_assist}" != "1" ]]; then
  log "Assist check skipped (supports_assist=false)"
  echo "LOCAL CHECK PASS"
  exit 0
fi

log "Checking ${BASE_URL}/v1/assist"
assist_json="$(curl -fsS --max-time "${DOCOPS_CHECK_ASSIST_TIMEOUT}" -X POST "${BASE_URL}/v1/assist" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"请给我1条会议通知写作建议。","skill":"meeting_notice"}')"

assist_info="$("${PYTHON_BIN}" -c '
import json
import sys

obj = json.loads(sys.argv[1])
if obj.get("ok") is not True:
    raise SystemExit("assist.ok != true")
answer = (obj.get("answer") or "").strip()
if not answer:
    raise SystemExit("assist.answer empty")
print(obj.get("model") or "")
print(obj.get("request_id") or "")
' "${assist_json}")"

assist_model="$(printf '%s' "${assist_info}" | sed -n '1p')"
assist_request_id="$(printf '%s' "${assist_info}" | sed -n '2p')"
log "Assist OK (model=${assist_model}, request_id=${assist_request_id})"

echo "LOCAL CHECK PASS"
