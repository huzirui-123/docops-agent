"""Utilities for docx XML operations.

All XML-level operations on docx content must be implemented here.
Do not spread XML manipulation logic across other modules.
"""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph
from docx.text.run import Run


def paragraph_has_direct_numpr(paragraph: Paragraph) -> bool:
    """Return True when paragraph has direct pPr.numPr (no style inheritance lookup)."""

    p_pr = paragraph._p.pPr
    if p_pr is None:
        return False
    return p_pr.find(qn("w:numPr")) is not None


def ensure_paragraph_direct_numpr(paragraph: Paragraph) -> None:
    """Ensure paragraph has direct pPr.numPr. Used for controlled tests."""

    p_pr = paragraph._p.get_or_add_pPr()
    if p_pr.find(qn("w:numPr")) is None:
        p_pr.append(OxmlElement("w:numPr"))


def remove_paragraph_direct_numpr(paragraph: Paragraph) -> bool:
    """Remove direct pPr.numPr and return whether a removal occurred."""

    p_pr = paragraph._p.pPr
    if p_pr is None:
        return False

    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        return False

    p_pr.remove(num_pr)
    return True


def get_line_spacing_twips(paragraph: Paragraph) -> int | None:
    """Return direct line spacing twips.

    Returns None when spacing is auto or cannot be determined.
    """

    p_pr = paragraph._p.pPr
    if p_pr is None:
        return None

    spacing = p_pr.find(qn("w:spacing"))
    if spacing is None:
        return None

    line_rule = spacing.get(qn("w:lineRule"))
    if line_rule in (None, "auto"):
        return None

    line_value = spacing.get(qn("w:line"))
    if line_value is None:
        return None

    try:
        return int(line_value)
    except ValueError:
        return None


def get_first_line_indent_twips(paragraph: Paragraph) -> int | None:
    """Return direct first-line indent twips or None when unavailable."""

    p_pr = paragraph._p.pPr
    if p_pr is None:
        return None

    ind = p_pr.find(qn("w:ind"))
    if ind is None:
        return None

    first_line = ind.get(qn("w:firstLine"))
    if first_line is None:
        return None

    try:
        return int(first_line)
    except ValueError:
        return None


def get_run_east_asia_font(run: Run) -> str | None:
    """Return run eastAsia font name from direct rPr.rFonts, if present."""

    r_pr = run._r.rPr
    if r_pr is None or r_pr.rFonts is None:
        return None
    return r_pr.rFonts.get(qn("w:eastAsia"))


def set_run_fonts_and_size(run: Run, latin_font: str, east_asia_font: str, size_pt: int) -> None:
    """Set direct run latin/eastAsia fonts and font size."""

    run.font.name = latin_font
    run.font.size = Pt(size_pt)

    r_pr = run._r.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)

    r_fonts.set(qn("w:ascii"), latin_font)
    r_fonts.set(qn("w:hAnsi"), latin_font)
    r_fonts.set(qn("w:eastAsia"), east_asia_font)
