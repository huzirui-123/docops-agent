"""Optional debug dump collection for suspicious rendered runs."""

from __future__ import annotations

import unicodedata

from docx.document import Document as DocxDocument
from pydantic import BaseModel, ConfigDict, Field

from core.format.run_ids import iter_paragraph_run_contexts
from core.utils.docx_xml import get_run_font_info

_SUSPICIOUS_CATEGORIES = {"So", "Cf", "Cs", "Co", "Cc"}
_SYMBOL_FONTS = {
    "symbol",
    "wingdings",
    "wingdings 2",
    "wingdings 3",
    "webdings",
    "mt extra",
}


class DebugCodepoint(BaseModel):
    """Character-level unicode details for suspicious runs."""

    model_config = ConfigDict(extra="forbid")

    index: int
    char: str
    codepoint: str
    category: str
    unicode_name: str | None = None


class DebugRunRecord(BaseModel):
    """One suspicious run entry in debug report."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    run_id: str
    paragraph_path: str
    touched: bool
    text_repr: str
    codepoints: list[DebugCodepoint] = Field(default_factory=list)
    font_info: dict[str, str | None]
    reasons: list[str] = Field(default_factory=list)


class DebugReport(BaseModel):
    """Debug dump payload for symbol/suspicious character diagnosis."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    scanned_runs: int
    suspicious_runs: list[DebugRunRecord] = Field(default_factory=list)


def collect_suspicious_runs(
    document: DocxDocument, touched_runs: set[str], stage: str
) -> DebugReport:
    """Collect suspicious runs from body and table paragraphs."""

    suspicious_runs: list[DebugRunRecord] = []
    scanned_runs = 0

    for context in iter_paragraph_run_contexts(document, include_tables=True):
        for run_id, run in zip(context.run_ids, context.paragraph.runs, strict=False):
            scanned_runs += 1
            text = run.text or ""
            font_info = get_run_font_info(run)
            reasons: list[str] = []

            if _has_symbol_font(font_info):
                reasons.append("symbol_font")

            category_hits = _collect_suspicious_categories(text)
            for category in category_hits:
                reasons.append(f"unicode_category:{category}")

            if not reasons:
                continue

            suspicious_runs.append(
                DebugRunRecord(
                    stage=stage,
                    run_id=run_id,
                    paragraph_path=context.paragraph_path,
                    touched=run_id in touched_runs,
                    text_repr=repr(text),
                    codepoints=_render_codepoints(text),
                    font_info=font_info,
                    reasons=reasons,
                )
            )

    return DebugReport(stage=stage, scanned_runs=scanned_runs, suspicious_runs=suspicious_runs)


def _has_symbol_font(font_info: dict[str, str | None]) -> bool:
    for key in ("name", "ascii", "hAnsi", "eastAsia", "cs"):
        value = font_info.get(key)
        if value is None:
            continue
        if value.strip().lower() in _SYMBOL_FONTS:
            return True
    return False


def _collect_suspicious_categories(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for char in text:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category in _SUSPICIOUS_CATEGORIES and category not in seen:
            seen.add(category)
            ordered.append(category)
    return ordered


def _render_codepoints(text: str) -> list[DebugCodepoint]:
    points: list[DebugCodepoint] = []
    for index, char in enumerate(text):
        code = f"U+{ord(char):04X}"
        points.append(
            DebugCodepoint(
                index=index,
                char=char,
                codepoint=code,
                category=unicodedata.category(char),
                unicode_name=unicodedata.name(char, None),
            )
        )
    return points
