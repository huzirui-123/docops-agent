"""Meeting notice skill without LLM dependencies."""

from __future__ import annotations

from core.skills.models import SkillResult, TaskSpec


class MeetingNoticeSkill:
    """Deterministically maps meeting payload fields to template placeholders."""

    name = "meeting_notice"

    _mapping = {
        "meeting_title": "MEETING_TITLE",
        "meeting_date": "MEETING_DATE",
        "meeting_time": "MEETING_TIME",
        "meeting_location": "MEETING_LOCATION",
        "organizer": "ORGANIZER",
        "attendees": "ATTENDEES",
    }

    _required_payload_keys = {
        "meeting_title",
        "meeting_date",
        "meeting_time",
        "meeting_location",
        "organizer",
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
