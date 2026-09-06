"""Markdown stitching and DOCX rendering."""

from __future__ import annotations

import re
from pathlib import Path

DOC_TEMPLATE = """# {title}

{meta_block}

---

{toc}

---

{body}

---

{traffic_light}

---

## Disclaimer

{disclaimer}
"""


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "document"


def estimate_pages(words: int) -> float:
    return round(words / 500, 1)


def render_document_markdown(
    *,
    title: str,
    meta: dict,
    toc: str,
    body: str,
    traffic_light_markdown: str,
    disclaimer: str,
) -> str:
    meta_block = "\n".join(f"**{k}:** {v}  " for k, v in meta.items())
    return DOC_TEMPLATE.format(
        title=title,
        meta_block=meta_block,
        toc=toc,
        body=body,
        traffic_light=traffic_light_markdown,
        disclaimer=disclaimer,
    )


def write_markdown(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- DOCX -----------------------------------------------------------------
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _add_runs(paragraph, text: str) -> None:
    """Render **bold** inline; everything else is a plain run."""
    pos = 0
    for match in _BOLD.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos : match.start()])
        paragraph.add_run(match.group(1)).bold = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _add_field(paragraph, instruction: str) -> None:
    """Insert a real Word field (used for the TOC and page numbers)."""
    from docx.oxml.ns import qn
    from docx.oxml.shared import OxmlElement

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instr, end):
        run._r.append(element)


def render_docx(*, markdown_text: str, path: Path, title: str, meta: dict, disclaimer: str) -> Path:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
        from docx.shared import Pt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("python-docx is required for DOCX output: pip install python-docx") from exc

    doc = Document()
    doc.core_properties.title = title
    doc.core_properties.author = "Legafy AI — Akridion Labs"
    doc.core_properties.comments = disclaimer[:250]  # Word caps this property at 255 chars

    # Title page.
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for key, value in meta.items():
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run(f"{key}: ").bold = True
        para.add_run(str(value))
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # Word-native TOC so the document paginates for real.
    doc.add_heading("Table of Contents", level=1)
    _add_field(doc.add_paragraph(), r'TOC \o "1-3" \h \z \u')
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if match := _HEADING.match(stripped):
            level = min(len(match.group(1)), 4)
            doc.add_heading(match.group(2).replace("**", ""), level=level)
        elif match := _BULLET.match(stripped):
            _add_runs(doc.add_paragraph(style="List Bullet"), match.group(1))
        elif match := _NUMBERED.match(stripped):
            _add_runs(doc.add_paragraph(style="List Number"), match.group(1))
        else:
            _add_runs(doc.add_paragraph(), stripped)

    # Footer: disclaimer + live page number on every page.
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(f"{disclaimer[:110]}…  |  Page ")
    run.font.size = Pt(7)
    _add_field(footer, "PAGE")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path
