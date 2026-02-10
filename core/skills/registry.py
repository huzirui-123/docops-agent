"""Skill registry for CLI/API skill resolution."""

from __future__ import annotations

from collections.abc import Callable

from core.skills.base import Skill
from core.skills.meeting_notice import MeetingNoticeSkill

SkillFactory = Callable[[], Skill]

_SUPPORTED_SKILLS: dict[str, SkillFactory] = {
    "meeting_notice": MeetingNoticeSkill,
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
