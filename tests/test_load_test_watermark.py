from __future__ import annotations

from pathlib import Path

from scripts.load_test import _tmp_summary_fields, scan_tmp_watermark


def test_scan_tmp_watermark_and_delta_fields(tmp_path: Path) -> None:
    root = tmp_path / "tmp-root"
    root.mkdir(parents=True, exist_ok=True)

    before = scan_tmp_watermark(root)
    assert before.count == 0
    assert before.bytes == 0

    (root / "a.txt").write_text("12345", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "b.bin").write_bytes(b"x" * 8)

    after = scan_tmp_watermark(root)
    assert after.count == 2
    assert after.bytes >= 13

    fields = _tmp_summary_fields(tmp_root=root, before=before, after=after)
    assert fields["tmp_root"] == str(root)
    assert fields["tmp_before_count"] == 0
    assert fields["tmp_after_count"] == 2
    assert fields["tmp_delta_count"] == 2
    assert fields["tmp_after_bytes"] >= fields["tmp_before_bytes"]


def test_tmp_summary_fields_when_disabled() -> None:
    fields = _tmp_summary_fields(tmp_root=None, before=None, after=None)
    assert fields["tmp_root"] is None
    assert fields["tmp_before_count"] is None
    assert fields["tmp_after_count"] is None
    assert fields["tmp_delta_count"] is None
    assert fields["tmp_warnings"] == []
