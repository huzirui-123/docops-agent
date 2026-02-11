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
- `DOCOPS_ENABLE_WEB_CONSOLE` (default: `1`)
- `DOCOPS_ENABLE_META` (default: `1`)
- `DOCOPS_WEB_BASIC_AUTH` (default: unset, format: `user:pass`)

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

- These toggles do **not** change `/v1/run` semantics.
- If using Nginx in front of the service, set:
  - `client_max_body_size >= DOCOPS_MAX_UPLOAD_BYTES`
  - otherwise uploads can be rejected before reaching the app.

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

## Behavioral Contract (unchanged)

- Strict format failure still returns `200 + zip` with `X-Docops-Exit-Code: 4`.
- Missing required fields still return `200 + zip` with `X-Docops-Exit-Code: 2`.
- `400/408/413/429/500` return JSON errors and do not return zip artifacts.
