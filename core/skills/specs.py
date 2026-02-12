"""Skill contract specs used by deterministic skill implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class SkillSpec:
    """Contract for one skill's payload-to-placeholder mapping."""

    mapping: Mapping[str, str]
    required_payload_keys: frozenset[str]
    list_payload_keys: frozenset[str]


MEETING_NOTICE_SPEC = SkillSpec(
    mapping=MappingProxyType(
        {
            "meeting_title": "MEETING_TITLE",
            "meeting_date": "MEETING_DATE",
            "meeting_time": "MEETING_TIME",
            "meeting_location": "MEETING_LOCATION",
            "organizer": "ORGANIZER",
            "attendees": "ATTENDEES",
        }
    ),
    required_payload_keys=frozenset(
        {
            "meeting_title",
            "meeting_date",
            "meeting_time",
            "meeting_location",
            "organizer",
        }
    ),
    list_payload_keys=frozenset({"attendees"}),
)


TRAINING_NOTICE_SPEC = SkillSpec(
    mapping=MappingProxyType(
        {
            "training_title": "TRAINING_TITLE",
            "training_date": "TRAINING_DATE",
            "training_time": "TRAINING_TIME",
            "training_location": "TRAINING_LOCATION",
            "trainer": "TRAINER",
            "organizer": "ORGANIZER",
            "attendees": "ATTENDEES",
        }
    ),
    required_payload_keys=frozenset(
        {
            "training_title",
            "training_date",
            "training_time",
            "training_location",
            "trainer",
        }
    ),
    list_payload_keys=frozenset({"attendees"}),
)


INSPECTION_RECORD_SPEC = SkillSpec(
    mapping=MappingProxyType(
        {
            "inspection_subject": "INSPECTION_SUBJECT",
            "inspection_date": "INSPECTION_DATE",
            "inspector": "INSPECTOR",
            "department": "DEPARTMENT",
            "issue_summary": "ISSUE_SUMMARY",
            "action_required": "ACTION_REQUIRED",
            "deadline": "DEADLINE",
        }
    ),
    required_payload_keys=frozenset(
        {
            "inspection_subject",
            "inspection_date",
            "inspector",
            "issue_summary",
        }
    ),
    list_payload_keys=frozenset(),
)


SKILL_SPECS: Mapping[str, SkillSpec] = MappingProxyType(
    {
        "meeting_notice": MEETING_NOTICE_SPEC,
        "training_notice": TRAINING_NOTICE_SPEC,
        "inspection_record": INSPECTION_RECORD_SPEC,
    }
)
