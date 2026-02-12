"""Shared helper for deterministic skill field construction."""

from __future__ import annotations

from core.skills.models import SkillResult, TaskSpec
from core.skills.specs import SkillSpec


def _render_payload_value(value: object, *, as_list: bool) -> str:
    """Render payload value to placeholder string with stable list behavior."""

    if as_list and isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def build_skill_result(task: TaskSpec, spec: SkillSpec) -> SkillResult:
    """Build ``SkillResult`` from task payload and a declarative skill spec."""

    field_values: dict[str, str] = {}
    for payload_key, placeholder in spec.mapping.items():
        value = task.payload.get(payload_key)
        if value is None:
            continue
        field_values[placeholder] = _render_payload_value(
            value, as_list=payload_key in spec.list_payload_keys
        )

    required_fields = {spec.mapping[key] for key in spec.required_payload_keys}
    optional_fields = set(spec.mapping.values()) - required_fields
    return SkillResult(
        field_values=field_values,
        required_fields=required_fields,
        optional_fields=optional_fields,
    )
