"""Local JSON store for template fingerprint mappings."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.templates.models import TemplateMapping, TemplateMapStoreData

_STORE_VERSION = 1


class TemplateMapStore:
    """Persist template mappings keyed by fingerprint in a JSON file."""

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path

    def get(self, fingerprint: str) -> TemplateMapping | None:
        data = self._read_data()
        return data.templates.get(fingerprint)

    def upsert(self, mapping: TemplateMapping) -> None:
        data = self._read_data()
        data.templates[mapping.fingerprint] = mapping
        self._write_data(data)

    def list_all(self) -> list[TemplateMapping]:
        data = self._read_data()
        return [data.templates[key] for key in sorted(data.templates.keys())]

    def delete(self, fingerprint: str) -> bool:
        data = self._read_data()
        if fingerprint not in data.templates:
            return False
        del data.templates[fingerprint]
        self._write_data(data)
        return True

    def _read_data(self) -> TemplateMapStoreData:
        if not self._store_path.exists():
            return TemplateMapStoreData(version=_STORE_VERSION)

        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid map store JSON: {self._store_path}") from exc

        templates_raw = raw.get("templates", {})
        templates: dict[str, TemplateMapping] = {}
        for fingerprint, item in templates_raw.items():
            templates[fingerprint] = TemplateMapping(
                fingerprint=item["fingerprint"],
                fields=list(item.get("fields", [])),
                field_map=dict(item.get("field_map", {})),
                note=item.get("note"),
            )

        version = int(raw.get("version", _STORE_VERSION))
        return TemplateMapStoreData(version=version, templates=templates)

    def _write_data(self, data: TemplateMapStoreData) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._store_path.with_suffix(f"{self._store_path.suffix}.tmp")

        payload = {
            "version": data.version,
            "templates": {
                key: asdict(data.templates[key]) for key in sorted(data.templates.keys())
            },
        }
        temp_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(self._store_path)
