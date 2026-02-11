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

## Environment Variables

- `DOCOPS_MAX_UPLOAD_BYTES` (default: `26214400`)
- `DOCOPS_REQUEST_TIMEOUT_SECONDS` (default: `60`)
- `DOCOPS_MAX_CONCURRENCY` (default: `2`)
- `DOCOPS_QUEUE_TIMEOUT_SECONDS` (default: `0`)
- `DOCOPS_MP_START` (default: `spawn`)
- `DOCOPS_DEBUG_ARTIFACTS` (default: `0`)

## Behavioral Contract (unchanged)

- Strict format failure still returns `200 + zip` with `X-Docops-Exit-Code: 4`.
- Missing required fields still return `200 + zip` with `X-Docops-Exit-Code: 2`.
- `400/408/413/429/500` return JSON errors and do not return zip artifacts.
