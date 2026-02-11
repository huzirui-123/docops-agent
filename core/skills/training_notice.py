"""Training notice skill without LLM dependencies."""

from __future__ import annotations

from core.skills.models import SkillResult, TaskSpec


class TrainingNoticeSkill:
    """Deterministically maps training payload fields to placeholders."""

    name = "training_notice"

    _mapping = {
        "training_title": "TRAINING_TITLE",
        "training_date": "TRAINING_DATE",
        "training_time": "TRAINING_TIME",
        "training_location": "TRAINING_LOCATION",
        "trainer": "TRAINER",
        "organizer": "ORGANIZER",
        "attendees": "ATTENDEES",
    }

    _required_payload_keys = {
        "training_title",
        "training_date",
        "training_time",
        "training_location",
        "trainer",
    }

    def build_fields(self, task: TaskSpec) -> SkillResult:
        field_values: dict[str, str] = {}

        for source_key, target_key in self._mapping.items():
            value = task.payload.get(source_key)
            if value is None:
                continue
            if isinstance(value, list):
                rendered = ", ".join(str(item) for item in value)
            else:
                rendered = str(value)
            field_values[target_key] = rendered

        required_fields = {self._mapping[key] for key in self._required_payload_keys}
        optional_fields = set(self._mapping.values()) - required_fields

        return SkillResult(
            field_values=field_values,
            required_fields=required_fields,
            optional_fields=optional_fields,
        )
