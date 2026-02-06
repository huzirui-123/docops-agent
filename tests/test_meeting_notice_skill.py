from __future__ import annotations

from core.skills.meeting_notice import MeetingNoticeSkill
from core.skills.models import TaskSpec


def test_meeting_notice_skill_maps_payload_fields() -> None:
    skill = MeetingNoticeSkill()
    task = TaskSpec(
        task_type="meeting_notice",
        payload={
            "meeting_title": "Weekly Sync",
            "meeting_date": "2026-02-06",
            "meeting_time": "10:00",
            "meeting_location": "Room 1",
            "organizer": "Alice",
            "attendees": ["A", "B"],
        },
    )

    result = skill.build_fields(task)

    assert result.field_values["MEETING_TITLE"] == "Weekly Sync"
    assert result.field_values["ATTENDEES"] == "A, B"


def test_meeting_notice_skill_required_optional_sets() -> None:
    skill = MeetingNoticeSkill()
    task = TaskSpec(task_type="meeting_notice", payload={})

    result = skill.build_fields(task)

    assert result.required_fields == {
        "MEETING_TITLE",
        "MEETING_DATE",
        "MEETING_TIME",
        "MEETING_LOCATION",
        "ORGANIZER",
    }
    assert result.optional_fields == {"ATTENDEES"}
