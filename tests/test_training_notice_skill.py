from __future__ import annotations

from core.skills.models import TaskSpec
from core.skills.training_notice import TrainingNoticeSkill


def test_training_notice_skill_maps_payload_fields() -> None:
    skill = TrainingNoticeSkill()
    task = TaskSpec(
        task_type="training_notice",
        payload={
            "training_title": "Safety Basics",
            "training_date": "2026-03-01",
            "training_time": "09:00-11:00",
            "training_location": "Room A",
            "trainer": "Coach Wang",
            "organizer": "Engineering",
            "attendees": ["A", "B"],
        },
    )

    result = skill.build_fields(task)

    assert result.field_values["TRAINING_TITLE"] == "Safety Basics"
    assert result.field_values["ATTENDEES"] == "A, B"


def test_training_notice_skill_required_optional_sets() -> None:
    skill = TrainingNoticeSkill()
    task = TaskSpec(task_type="training_notice", payload={})

    result = skill.build_fields(task)

    assert result.required_fields == {
        "TRAINING_TITLE",
        "TRAINING_DATE",
        "TRAINING_TIME",
        "TRAINING_LOCATION",
        "TRAINER",
    }
    assert result.optional_fields == {"ORGANIZER", "ATTENDEES"}
