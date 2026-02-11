"""Inspection record skill without LLM dependencies."""

from __future__ import annotations

from core.skills.models import SkillResult, TaskSpec


class InspectionRecordSkill:
    """Deterministically maps inspection payload fields to placeholders."""

    name = "inspection_record"

    _mapping = {
        "inspection_subject": "INSPECTION_SUBJECT",
        "inspection_date": "INSPECTION_DATE",
        "inspector": "INSPECTOR",
        "department": "DEPARTMENT",
        "issue_summary": "ISSUE_SUMMARY",
        "action_required": "ACTION_REQUIRED",
        "deadline": "DEADLINE",
    }

    _required_payload_keys = {
        "inspection_subject",
        "inspection_date",
        "inspector",
        "issue_summary",
    }

    def build_fields(self, task: TaskSpec) -> SkillResult:
        field_values: dict[str, str] = {}

        for source_key, target_key in self._mapping.items():
            value = task.payload.get(source_key)
            if value is None:
                continue
            field_values[target_key] = str(value)

        required_fields = {self._mapping[key] for key in self._required_payload_keys}
        optional_fields = set(self._mapping.values()) - required_fields

        return SkillResult(
            field_values=field_values,
            required_fields=required_fields,
            optional_fields=optional_fields,
        )
