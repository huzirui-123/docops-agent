from __future__ import annotations

from pathlib import Path

from scripts.check_tmp_watermark import scan_watermark


def test_scan_watermark_counts_bytes_and_top_n(tmp_path: Path) -> None:
    root = tmp_path / "watermark"
    root.mkdir(parents=True, exist_ok=True)

    large_dir = root / "dir_large"
    large_dir.mkdir(parents=True, exist_ok=True)
    (large_dir / "a.bin").write_bytes(b"a" * 64)
    (large_dir / "b.bin").write_bytes(b"b" * 32)

    small_file = root / "small.txt"
    small_file.write_text("hello", encoding="utf-8")

    stats = scan_watermark(root, top_n=2)
    assert stats.count == 3
    assert stats.bytes >= 101
    assert len(stats.top_n) == 2
    assert stats.top_n[0].bytes >= stats.top_n[1].bytes


def test_scan_watermark_missing_root_is_safe(tmp_path: Path) -> None:
    missing = tmp_path / "missing-root"
    stats = scan_watermark(missing, top_n=10)

    assert stats.count == 0
    assert stats.bytes == 0
    assert stats.top_n == []
    assert any(item.startswith("root_not_found:") for item in stats.warnings)
