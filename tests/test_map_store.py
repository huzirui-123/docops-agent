from __future__ import annotations

from pathlib import Path

import pytest

from core.templates.map_store import TemplateMapStore
from core.templates.models import TemplateMapping


def test_map_store_initializes_empty_data(tmp_path: Path) -> None:
    store = TemplateMapStore(tmp_path / "template_map.json")

    assert store.list_all() == []
    assert store.get("missing") is None


def test_map_store_upsert_and_get_round_trip(tmp_path: Path) -> None:
    store = TemplateMapStore(tmp_path / "template_map.json")
    mapping = TemplateMapping(
        fingerprint="fp-1",
        fields=["A", "B"],
        field_map={"A": "alpha", "B": "beta"},
        note="test",
    )

    store.upsert(mapping)

    loaded = store.get("fp-1")
    assert loaded == mapping


def test_map_store_upsert_overwrites_existing_mapping(tmp_path: Path) -> None:
    store = TemplateMapStore(tmp_path / "template_map.json")
    store.upsert(TemplateMapping(fingerprint="fp-1", fields=["A"], field_map={"A": "x"}))
    store.upsert(TemplateMapping(fingerprint="fp-1", fields=["A", "B"], field_map={"B": "y"}))

    loaded = store.get("fp-1")
    assert loaded is not None
    assert loaded.fields == ["A", "B"]
    assert loaded.field_map == {"B": "y"}


def test_map_store_list_all_is_sorted_by_fingerprint(tmp_path: Path) -> None:
    store = TemplateMapStore(tmp_path / "template_map.json")
    store.upsert(TemplateMapping(fingerprint="fp-2"))
    store.upsert(TemplateMapping(fingerprint="fp-1"))

    result = store.list_all()

    assert [item.fingerprint for item in result] == ["fp-1", "fp-2"]


def test_map_store_delete_removes_mapping(tmp_path: Path) -> None:
    store = TemplateMapStore(tmp_path / "template_map.json")
    store.upsert(TemplateMapping(fingerprint="fp-1"))

    assert store.delete("fp-1") is True
    assert store.get("fp-1") is None
    assert store.delete("fp-1") is False


def test_map_store_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "template_map.json"

    store_a = TemplateMapStore(path)
    store_a.upsert(TemplateMapping(fingerprint="fp-1", fields=["NAME"], field_map={"NAME": "n"}))

    store_b = TemplateMapStore(path)
    loaded = store_b.get("fp-1")

    assert loaded is not None
    assert loaded.fields == ["NAME"]
    assert loaded.field_map == {"NAME": "n"}


def test_map_store_raises_on_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "template_map.json"
    path.write_text("{invalid", encoding="utf-8")
    store = TemplateMapStore(path)

    with pytest.raises(ValueError, match="Invalid map store JSON"):
        store.list_all()
