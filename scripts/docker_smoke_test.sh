#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="docops-agent:local"
BASE_IMAGE="python:3.11-slim"
CONTAINER_NAME="docops_agent_smoke"
BASE_URL=""
HOST_PORT=""

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"; docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true' EXIT

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  return 1
}

PYTHON_BIN="$(pick_python)" || {
  echo "docker_smoke_test.sh requires python3 or python in PATH" >&2
  exit 1
}

json_assert() {
  local file_path="$1"
  local python_code="$2"
  "${PYTHON_BIN}" - "$file_path" "$python_code" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
code = sys.argv[2]
obj = json.loads(path.read_text(encoding="utf-8"))
if not eval(code, {"obj": obj}):
    raise SystemExit(f"JSON assertion failed: {code}; payload={obj}")
PY
}

header_value() {
  local header_file="$1"
  local header_name="$2"
  "${PYTHON_BIN}" - "$header_file" "$header_name" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
key = sys.argv[2].lower()
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if ":" not in line:
        continue
    name, value = line.split(":", 1)
    if name.strip().lower() == key:
        print(value.strip())
        raise SystemExit(0)
print("")
PY
}

ensure_docker_available() {
  if ! docker version >/dev/null 2>&1; then
    echo "[docker-smoke] Docker daemon unavailable (blocked): cannot run smoke test" >&2
    exit 2
  fi
}

ensure_base_image() {
  if docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1; then
    return 0
  fi

  local attempt=1
  local max_attempts=3
  local sleep_seconds=2

  while (( attempt <= max_attempts )); do
    echo "[docker-smoke] Pulling ${BASE_IMAGE} (attempt ${attempt}/${max_attempts})..."
    if docker pull "${BASE_IMAGE}"; then
      return 0
    fi
    if (( attempt == max_attempts )); then
      echo "[docker-smoke] Failed to pull ${BASE_IMAGE} after ${max_attempts} attempts" >&2
      return 1
    fi
    sleep "${sleep_seconds}"
    sleep_seconds=$((sleep_seconds * 2))
    attempt=$((attempt + 1))
  done

  return 1
}

wait_for_health() {
  local deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    local status
    status="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/healthz" 2>/dev/null || true)"
    if [[ "${status}" == "200" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "[docker-smoke] Service did not become healthy within timeout at ${BASE_URL}" >&2
  echo "[docker-smoke] Container logs:" >&2
  docker logs "${CONTAINER_NAME}" >&2 || true
  return 1
}

start_container_with_fallback_port() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

  local start_port=8000
  local end_port=8019
  local port

  for ((port=start_port; port<=end_port; port++)); do
    echo "[docker-smoke] Trying port ${port}..."
    if docker run -d --rm -p "${port}:8000" --name "${CONTAINER_NAME}" "$@" "${IMAGE_TAG}" >/dev/null 2>&1; then
      HOST_PORT="${port}"
      BASE_URL="http://127.0.0.1:${HOST_PORT}"
      return 0
    fi
  done

  echo "[docker-smoke] Failed to start container on ports ${start_port}-${end_port}" >&2
  docker logs "${CONTAINER_NAME}" >&2 || true
  return 1
}

run_container() {
  start_container_with_fallback_port "$@"
  wait_for_health
}

request_to_files() {
  local url="$1"
  local body_file="$2"
  local headers_file="$3"
  curl -sS -o "$body_file" -D "$headers_file" -w '%{http_code}' "$url"
}

ensure_docker_available
ensure_base_image

echo "[docker-smoke] Building image ${IMAGE_TAG}..."
docker build -t "${IMAGE_TAG}" .

echo "[docker-smoke] Starting container with default env..."
run_container

echo "[docker-smoke] Using BASE_URL=${BASE_URL}"

healthz_body="${TMP_DIR}/healthz.json"
healthz_headers="${TMP_DIR}/healthz.headers"
healthz_status="$(request_to_files "${BASE_URL}/healthz" "$healthz_body" "$healthz_headers")"
[[ "$healthz_status" == "200" ]]
json_assert "$healthz_body" 'obj.get("status") == "ok"'

health_body="${TMP_DIR}/health.json"
health_headers="${TMP_DIR}/health.headers"
health_status="$(request_to_files "${BASE_URL}/health" "$health_body" "$health_headers")"
[[ "$health_status" == "200" ]]
json_assert "$health_body" 'obj.get("ok") is True'

web_body="${TMP_DIR}/web_default.json"
web_headers="${TMP_DIR}/web_default.headers"
web_status="$(request_to_files "${BASE_URL}/web" "$web_body" "$web_headers")"
[[ "$web_status" == "404" ]]
web_req_id="$(header_value "$web_headers" "X-Docops-Request-Id")"
[[ -n "$web_req_id" ]]

meta_body="${TMP_DIR}/meta.json"
meta_headers="${TMP_DIR}/meta.headers"
meta_status="$(request_to_files "${BASE_URL}/v1/meta" "$meta_body" "$meta_headers")"
if [[ "$meta_status" == "200" ]]; then
  json_assert "$meta_body" '"supported_skills" in obj and isinstance(obj["supported_skills"], list)'
else
  echo "[docker-smoke] meta disabled or unavailable (status=${meta_status}), continuing"
fi

echo "[docker-smoke] Restarting container with DOCOPS_ENABLE_WEB_CONSOLE=1..."
run_container -e DOCOPS_ENABLE_WEB_CONSOLE=1

echo "[docker-smoke] Using BASE_URL=${BASE_URL}"

web_enabled_body="${TMP_DIR}/web_enabled.html"
web_enabled_headers="${TMP_DIR}/web_enabled.headers"
web_enabled_status="$(request_to_files "${BASE_URL}/web" "$web_enabled_body" "$web_enabled_headers")"
[[ "$web_enabled_status" == "200" ]]
grep -q "DocOps Web Console" "$web_enabled_body"

echo "SMOKE PASS"
