from __future__ import annotations

from pathlib import Path

import pytest

from core.format.policy_loader import load_policy


def test_load_default_policy() -> None:
    policy = load_policy()

    assert policy.run_font_latin == "Calibri"
    assert policy.run_font_east_asia == "宋体"
    assert policy.forbid_tables is True


def test_load_policy_raises_for_invalid_type(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
forbid_tables: true
forbid_numpr: true
numpr_direct_only: true
run_font_latin: BUSINESS_DEFAULT_LATIN
run_font_east_asia: BUSINESS_DEFAULT_EAST_ASIA
run_size_pt: bad_type
line_spacing_twips: 360
first_line_indent_twips: 420
twips_tolerance: 20
trim_leading_spaces: true
trim_chars: [" ", "\\t", "\\u3000"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid policy schema"):
        load_policy(path)


def test_load_policy_raises_for_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
forbid_tables: true
forbid_numpr: true
numpr_direct_only: true
run_font_latin: BUSINESS_DEFAULT_LATIN
run_size_pt: 12
line_spacing_twips: 360
first_line_indent_twips: 420
twips_tolerance: 20
trim_leading_spaces: true
trim_chars: [" ", "\\t", "\\u3000"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid policy schema"):
        load_policy(path)


def test_load_policy_maps_legacy_font_tokens(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
forbid_tables: true
forbid_numpr: true
numpr_direct_only: true
run_font_latin: BUSINESS_DEFAULT_LATIN
run_font_east_asia: BUSINESS_DEFAULT_EAST_ASIA
run_size_pt: 12
line_spacing_twips: 360
first_line_indent_twips: 420
twips_tolerance: 20
trim_leading_spaces: true
trim_chars: [" ", "\\t", "\\u3000"]
""",
        encoding="utf-8",
    )

    policy = load_policy(path)
    assert policy.run_font_latin == "Calibri"
    assert policy.run_font_east_asia == "宋体"


def test_load_policy_raises_for_unknown_font_token(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
forbid_tables: true
forbid_numpr: true
numpr_direct_only: true
run_font_latin: BUSINESS_DEFAULT_UNKNOWN
run_font_east_asia: 宋体
run_size_pt: 12
line_spacing_twips: 360
first_line_indent_twips: 420
twips_tolerance: 20
trim_leading_spaces: true
trim_chars: [" ", "\\t", "\\u3000"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid policy font token"):
        load_policy(path)
