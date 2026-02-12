"""Skill registry for CLI/API skill resolution."""

from __future__ import annotations

from collections.abc import Callable

from core.skills.base import Skill
from core.skills.inspection_record import InspectionRecordSkill
from core.skills.meeting_notice import MeetingNoticeSkill
from core.skills.models import supported_task_types
from core.skills.specs import SKILL_SPECS
from core.skills.training_notice import TrainingNoticeSkill

SkillFactory = Callable[[], Skill]

_SUPPORTED_SKILLS: dict[str, SkillFactory] = {
    "inspection_record": InspectionRecordSkill,
    "meeting_notice": MeetingNoticeSkill,
    "training_notice": TrainingNoticeSkill,
}


def create_skill(name: str) -> Skill:
    """Instantiate a supported skill by name."""

    try:
        factory = _SUPPORTED_SKILLS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported skill: {name}") from exc
    return factory()


def list_supported_skills() -> list[str]:
    """Return supported skill names in stable order."""

    return sorted(_SUPPORTED_SKILLS)


def _assert_registry_alignment() -> None:
    """Fail fast when model/spec support diverges from skill registry keys."""

    skill_names = set(_SUPPORTED_SKILLS)
    task_types = set(supported_task_types())
    spec_names = set(SKILL_SPECS)
    if skill_names != task_types or skill_names != spec_names:
        raise RuntimeError(
            "Skill registry/spec keys must match task type schemas: "
            "skills="
            f"{sorted(skill_names)}, task_types={sorted(task_types)}, specs={sorted(spec_names)}"
        )


_assert_registry_alignment()
