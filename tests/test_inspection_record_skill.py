from __future__ import annotations

from core.skills.inspection_record import InspectionRecordSkill
from core.skills.models import TaskSpec


def test_inspection_record_skill_maps_payload_fields() -> None:
    skill = InspectionRecordSkill()
    task = TaskSpec(
        task_type="inspection_record",
        payload={
            "inspection_subject": "Site A",
            "inspection_date": "2026-03-01",
            "inspector": "Li",
            "department": "Quality",
            "issue_summary": "No helmet",
            "action_required": "Safety retraining",
            "deadline": "2026-03-08",
        },
    )

    result = skill.build_fields(task)

    assert result.field_values["INSPECTION_SUBJECT"] == "Site A"
    assert result.field_values["ISSUE_SUMMARY"] == "No helmet"


def test_inspection_record_skill_required_optional_sets() -> None:
    skill = InspectionRecordSkill()
    task = TaskSpec(task_type="inspection_record", payload={})

    result = skill.build_fields(task)

    assert result.required_fields == {
        "INSPECTION_SUBJECT",
        "INSPECTION_DATE",
        "INSPECTOR",
        "ISSUE_SUMMARY",
    }
    assert result.optional_fields == {"DEPARTMENT", "ACTION_REQUIRED", "DEADLINE"}
