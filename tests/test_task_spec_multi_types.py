from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.skills.models import TaskSpec


def test_task_spec_validates_meeting_notice_payload() -> None:
    task = TaskSpec(
        task_type="meeting_notice",
        payload={"meeting_title": "Weekly Sync", "attendees": ["A", "B"]},
    )

    assert task.task_type == "meeting_notice"
    assert task.payload["meeting_title"] == "Weekly Sync"


def test_task_spec_validates_training_notice_payload() -> None:
    task = TaskSpec(
        task_type="training_notice",
        payload={"training_title": "Safety 101", "trainer": "Coach"},
    )

    assert task.task_type == "training_notice"
    assert task.payload["trainer"] == "Coach"


def test_task_spec_validates_inspection_record_payload() -> None:
    task = TaskSpec(
        task_type="inspection_record",
        payload={"inspection_subject": "Site A", "issue_summary": "No helmet"},
    )

    assert task.task_type == "inspection_record"
    assert task.payload["inspection_subject"] == "Site A"


def test_task_spec_rejects_unknown_task_type() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(task_type="unknown", payload={})


def test_task_spec_rejects_unknown_payload_key() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(
            task_type="training_notice",
            payload={"training_title": "Safety 101", "extra_key": "bad"},
        )


def test_task_spec_rejects_invalid_payload_type() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(task_type="inspection_record", payload={"inspection_date": 20260211})
