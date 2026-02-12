from __future__ import annotations

import re

import pytest

from core.skills.models import TASK_PAYLOAD_SCHEMAS
from core.skills.registry import list_supported_skills
from core.skills.specs import SKILL_SPECS


def test_registry_keys_align_with_task_types_and_specs() -> None:
    assert set(list_supported_skills()) == set(TASK_PAYLOAD_SCHEMAS)
    assert set(SKILL_SPECS) == set(TASK_PAYLOAD_SCHEMAS)


@pytest.mark.parametrize("skill_name", sorted(SKILL_SPECS))
def test_skill_spec_mapping_keys_align_with_payload_schema(skill_name: str) -> None:
    spec = SKILL_SPECS[skill_name]
    mapping_keys = set(spec.mapping)
    schema_fields = set(TASK_PAYLOAD_SCHEMAS[skill_name].model_fields)

    assert mapping_keys == schema_fields
    assert spec.required_payload_keys <= mapping_keys
    assert spec.list_payload_keys <= mapping_keys


@pytest.mark.parametrize("skill_name", sorted(SKILL_SPECS))
def test_skill_spec_placeholders_are_unique_and_stable(skill_name: str) -> None:
    placeholder_values = list(SKILL_SPECS[skill_name].mapping.values())

    assert len(placeholder_values) == len(set(placeholder_values))
    for placeholder in placeholder_values:
        assert re.fullmatch(r"[A-Z0-9_]+", placeholder) is not None
