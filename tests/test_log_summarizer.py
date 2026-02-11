from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_log_summarizer_json_output(tmp_path: Path) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "done",
                        "outcome": "ok",
                        "http_status": 200,
                        "queue_wait_ms": 10,
                        "timing": {"total_ms": 120},
                    }
                ),
                json.dumps(
                    {
                        "event": "error",
                        "outcome": "timeout",
                        "status_code": 408,
                        "queue_wait_ms": 20,
                        "timing": {"total_ms": 320},
                    }
                ),
                "not-json-line",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/summarize_logs.py", "--json", str(log_path)],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["parse_errors"] == 1
    assert payload["outcome_counts"]["ok"] == 1
    assert payload["outcome_counts"]["timeout"] == 1
    assert payload["http_status_counts"]["200"] == 1
    assert payload["http_status_counts"]["408"] == 1
    assert payload["queue_wait_ms_p95"] == 20
    assert payload["total_ms_p95"] == 320
