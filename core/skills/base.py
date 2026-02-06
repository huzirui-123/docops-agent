"""Skill interface definitions."""

from __future__ import annotations

from typing import Protocol

from core.skills.models import SkillResult, TaskSpec


class Skill(Protocol):
    """Protocol for deterministic skill implementations."""

    name: str

    def build_fields(self, task: TaskSpec) -> SkillResult:
        """Build template field values from a task specification."""
