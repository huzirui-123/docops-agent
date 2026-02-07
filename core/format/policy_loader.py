"""Policy loading utilities for format validation/fixing."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from core.format.models import FormatPolicy

_FONT_TOKEN_MAP = {
    "BUSINESS_DEFAULT_LATIN": "Calibri",
    "BUSINESS_DEFAULT_EAST_ASIA": "宋体",
}


def load_policy(path: Path | None = None) -> FormatPolicy:
    """Load and validate formatting policy from YAML."""

    policy_path = path or Path(__file__).with_name("policy.yaml")

    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Policy file not found: {policy_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in policy file: {policy_path}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Policy file must contain a mapping: {policy_path}")

    normalized = _normalize_policy_fonts(raw, policy_path)

    try:
        return FormatPolicy.model_validate(normalized)
    except ValidationError as exc:
        raise ValueError(f"Invalid policy schema: {policy_path}") from exc


def _normalize_policy_fonts(raw: dict[object, object], policy_path: Path) -> dict[object, object]:
    normalized = dict(raw)
    for key in ("run_font_latin", "run_font_east_asia"):
        value = normalized.get(key)
        if not isinstance(value, str):
            continue
        if value in _FONT_TOKEN_MAP:
            normalized[key] = _FONT_TOKEN_MAP[value]
            continue
        if value.startswith("BUSINESS_DEFAULT_"):
            raise ValueError(
                f"Invalid policy font token '{value}' in {policy_path}. "
                "Use a real font name or a supported default token."
            )
    return normalized
