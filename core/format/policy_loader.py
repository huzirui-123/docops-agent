"""Policy loading utilities for format validation/fixing."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from core.format.models import FormatPolicy


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

    try:
        return FormatPolicy.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid policy schema: {policy_path}") from exc
