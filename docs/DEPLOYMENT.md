# Deployment Guide

## Runtime Modes

### Development
```bash
poetry run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

### Production
```bash
poetry run gunicorn -k uvicorn.workers.UvicornWorker -w 2 apps.api.main:app
```

## Docker Deployment

Build and run with Docker:

```bash
docker build -t docops-agent:local .
docker run --rm -p 8000:8000 docops-agent:local
```

Or use Compose:

```bash
docker compose up --build
```

Runtime toggles are passed by environment variables. Defaults remain unchanged:

- `/web` stays disabled by default (`DOCOPS_ENABLE_WEB_CONSOLE=0`)
- optional CORS stays disabled by default (`DOCOPS_ENABLE_CORS=0`)

Example (enable web console + basic auth):

```bash
docker run --rm -p 8000:8000 \
  -e DOCOPS_ENABLE_WEB_CONSOLE=1 \
  -e DOCOPS_WEB_BASIC_AUTH=docops:change-me \
  docops-agent:local
```

For split frontend/browser access, both conditions are required:

- browser connect whitelist: `DOCOPS_WEB_CONNECT_SRC=...`
- API CORS response headers: `DOCOPS_ENABLE_CORS=1` and `DOCOPS_CORS_ALLOW_ORIGINS=...`

These deployment options do not change `/v1/run` business semantics or error body contract.

## Concurrency Model

- `DOCOPS_MAX_CONCURRENCY` is a per-process token limit.
- With multiple workers, total capacity is approximately:
  - `workers * DOCOPS_MAX_CONCURRENCY`
- `DOCOPS_QUEUE_TIMEOUT_SECONDS=0` means immediate `429 TOO_MANY_REQUESTS` when no slot is available.

## Subprocess Start Method

- `DOCOPS_MP_START` controls `multiprocessing` start method (default: `spawn`).
- Keep the same value across all workers to avoid behavior drift.
- `spawn` is recommended for predictable isolation.

## Timeout, Streaming, Cleanup

- Request timeout is controlled by `DOCOPS_REQUEST_TIMEOUT_SECONDS`.
- On timeout, API terminates/kills the worker subprocess and returns `408`.
- ZIP is returned with streaming response.
- Temporary files are cleaned after response completion via background cleanup.
- Middleware also performs best-effort cleanup for registered temporary paths when an uncaught exception becomes a `500` response.

## Environment Variables

- `DOCOPS_MAX_UPLOAD_BYTES` (default: `26214400`)
- `DOCOPS_REQUEST_TIMEOUT_SECONDS` (default: `60`)
- `DOCOPS_MAX_CONCURRENCY` (default: `2`)
- `DOCOPS_QUEUE_TIMEOUT_SECONDS` (default: `0`)
- `DOCOPS_MP_START` (default: `spawn`)
- `DOCOPS_DEBUG_ARTIFACTS` (default: `0`)
- `DOCOPS_ENABLE_WEB_CONSOLE` (default: `0`)
- `DOCOPS_ENABLE_META` (default: `1`)
- `DOCOPS_WEB_BASIC_AUTH` (default: unset, format: `user:pass`)
- `DOCOPS_ENABLE_CORS` (default: `0`)
- `DOCOPS_CORS_ALLOW_ORIGINS` (default when enabled and unset: `*`)
- `DOCOPS_CORS_ALLOW_CREDENTIALS` (default: `0`)
- `DOCOPS_CORS_MAX_AGE` (default: `600`)

## Security / Exposure

- `/web` and `/v1/meta` are convenience/debug endpoints.
- Production recommendation:
  - disable one or both endpoints, or
  - place API behind reverse-proxy authentication.

Example:
```bash
export DOCOPS_ENABLE_WEB_CONSOLE=0
export DOCOPS_ENABLE_META=1
export DOCOPS_WEB_BASIC_AUTH="docops:change-me"
```

Enable web console locally:
```bash
export DOCOPS_ENABLE_WEB_CONSOLE=1
```

- These toggles do **not** change `/v1/run` semantics.
- If using Nginx in front of the service, set:
  - `client_max_body_size >= DOCOPS_MAX_UPLOAD_BYTES`
  - otherwise uploads can be rejected before reaching the app.

## Optional CORS (default off)

For local split frontend debugging, you can enable CORS:

```bash
export DOCOPS_ENABLE_CORS=1
export DOCOPS_CORS_ALLOW_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
```

- CORS is disabled by default.
- When enabled, `X-Docops-Request-Id` is exposed to browsers.
- In production, keep origins strict and apply auth at reverse proxy.
- CORS settings do **not** change `/v1/run` business semantics or error body structure.

## Web Console (debug/demo only)

- `/web` remains gated by `DOCOPS_ENABLE_WEB_CONSOLE` (default: `0`).
- Enable locally:

```bash
export DOCOPS_ENABLE_WEB_CONSOLE=1
```

- UI usability features include:
  - Meta bootstrap (`Load Meta`)
  - Optional `API Base URL` for split frontend debugging
  - Request ID copy, duration display, readable error rendering
  - ZIP download on success
  - Reproduce snippet (`Copy curl`) for easy issue replay
  - Task JSON import/export
  - Local settings persistence (except template file input)
  - Recent request history (last 10 runs)
- For cross-origin browser calls, configure Optional CORS above.
- This UI layer does **not** change `/v1/run` status codes, error body schema, or artifact rules.

## Web Console Hardening

- `/web` and `/web/static/*` are protected by the same gate and optional BasicAuth:
  - `DOCOPS_ENABLE_WEB_CONSOLE=0` (default) disables access.
  - `DOCOPS_WEB_BASIC_AUTH="user:pass"` protects enabled endpoints.
- Web static responses include web-only security headers:
  - `Cache-Control: no-store, max-age=0`
  - `Pragma: no-cache`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: DENY`
  - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
  - `X-Robots-Tag: noindex, nofollow`
  - `Content-Security-Policy` with `script-src 'self'` and `frame-ancestors 'none'`
- CSP `connect-src` default is `'self'`. To allow cross-origin API calls from the console, you need both:
  - `DOCOPS_WEB_CONNECT_SRC="https://your-api-origin"` (browser connection whitelist)
  - Optional CORS enabled for API responses:
    - `DOCOPS_ENABLE_CORS=1`
    - `DOCOPS_CORS_ALLOW_ORIGINS=...`
- In short: cross-origin console access needs both `connect-src` allowlist and API CORS headers.
- For production exposure, keep `/web` behind reverse-proxy authentication for both routes:
  - `location /web`
  - `location /web/static/`

## Structured Logging

- API logs are single-line JSON via logger `docops.api`.
- `/v1/run` `event="done"` now includes:
  - `outcome`: `ok | missing_required | strict_failed | other_exit_code`
  - `http_status=200`
- `/v1/run` `event="error"` includes:
  - `outcome`: `bad_request | timeout | payload_too_large | rate_limited | internal_error`
- Logs never include template/task raw content or policy text values.

## Load Test Leak Check

Use:
```bash
python scripts/load_test.py \
  --base-url http://127.0.0.1:8000 \
  --concurrency 8 \
  --requests 20 \
  --check-subprocess-leaks \
  --leak-grace-ms 1500 \
  --tmp-root /tmp \
  --write-summary /tmp/docops-load-summary.json \
  --fail-on-leaks
```

- The script parses `api_result.json` from returned zip payloads and tracks observed subprocess pids when available.
- It then checks whether those pids still exist after a grace period.
- `leaked_pids` is always reported in summary.
- `--fail-on-leaks` makes leaked pids a hard failure (`exit 1`).
- `psutil` is optional; without it, platform fallback checks are used when possible.
- If `--tmp-root` is provided, summary includes tmp watermark before/after deltas:
  - `tmp_before_count/tmp_before_bytes`
  - `tmp_after_count/tmp_after_bytes`
  - `tmp_delta_count/tmp_delta_bytes`
  - `tmp_warnings`

## Tmp Watermark Utility

Use:
```bash
python scripts/check_tmp_watermark.py --root /tmp --json
```

- This utility is observational only and always exits with `0`.
- Output includes:
  - `count`
  - `bytes`
  - `top_n` (largest children under root)
  - `warnings`

## Log Summary Utility

Use:
```bash
python scripts/summarize_logs.py --json /var/log/docops-api.log
```

- Aggregates `outcome_counts` and `http_status_counts`.
- Computes latency percentiles when fields exist:
  - `queue_wait_ms_p50/p95`
  - `total_ms_p50/p95` (from `timing.total_ms`)
- Bad JSON lines are tolerated and counted in `parse_errors`.
- `outcome_counts` can be used directly for alerts/dashboards.

## CI Stability Smoke

Authoritative script entrypoints:
- `scripts/ci_smoke.py`
- `scripts/ci_thresholds.py`

Use:
```bash
poetry run python scripts/ci_smoke.py \
  --port 0 \
  --repeat 3 \
  --repeat-warmup 1 \
  --requests 20 \
  --concurrency 6 \
  --skill meeting_notice \
  --artifacts-dir artifacts
```

This runner will:
- start a local API server process
- auto-pick free port when `--port 0` is used
- wait for `/healthz`
- run `scripts/load_test.py` for multiple rounds
- run `scripts/summarize_logs.py`
- evaluate thresholds and write `artifacts/ci_result.json`
- write human-readable report `artifacts/ci_result.md`

Warmup rounds are excluded from threshold evaluation.
This reduces false positives from import/cache startup jitter.
Thresholds are evaluated on measurement rounds using worst-case aggregation.

Default threshold env vars (override as needed):
- `DOCOPS_CI_ALLOW_429=0`
- `DOCOPS_CI_MAX_TMP_DELTA_BYTES=5242880`
- `DOCOPS_CI_MAX_TMP_DELTA_COUNT=50`
- `DOCOPS_CI_MAX_TOTAL_MS_P95=15000`
- `DOCOPS_CI_MAX_QUEUE_WAIT_MS_P95=3000`
- `DOCOPS_CI_REQUIRE_NO_LEAKS=1`
- `DOCOPS_CI_REQUIRE_INTERNAL_ERROR_ZERO=1`
- `DOCOPS_CI_REQUIRE_NON_200_ZERO=1`

When CI smoke fails:
- check `artifacts/ci_result.md` first for quick diagnosis
- then inspect `artifacts/server.log` and `artifacts/log_summary.json`
- locally reproduce with the same command shown in `ci_result.md`
- in GitHub Actions, install uvicorn into Poetry venv:
  - `poetry run python -m pip install uvicorn`

## Behavioral Contract (unchanged)

- Strict format failure still returns `200 + zip` with `X-Docops-Exit-Code: 4`.
- Missing required fields still return `200 + zip` with `X-Docops-Exit-Code: 2`.
- `400/408/413/429/500` return JSON errors and do not return zip artifacts.
