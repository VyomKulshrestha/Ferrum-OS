#!/usr/bin/env python3
"""Build the OS-JEPA v3.4 research note PDF from its frozen Markdown source."""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "research" / "paper" / "when_agents_control_kernel_v1_1_research_note.md"
DEFAULT_OUTPUT = ROOT / "output" / "pdf" / "when_agents_control_kernel_v1_1_research_note.pdf"

INK = colors.HexColor("#162033")
MUTED = colors.HexColor("#526076")
NAVY = colors.HexColor("#173B57")
TEAL = colors.HexColor("#167A7A")
ORANGE = colors.HexColor("#E37B40")
PALE = colors.HexColor("#EDF4F6")
GRID = colors.HexColor("#CBD6DE")


def inline(text: str) -> str:
    value = escape(text.strip())
    value = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", value)
    value = re.sub(r"(https?://[^\s<]+)", r"<link href='\1' color='#167A7A'>\1</link>", value)
    return value


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=25, leading=29, textColor=NAVY, alignment=TA_LEFT,
            spaceAfter=7 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Heading2"], fontName="Helvetica",
            fontSize=15, leading=20, textColor=TEAL, alignment=TA_LEFT,
            spaceAfter=10 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, leading=16, textColor=MUTED,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=15, leading=19, textColor=NAVY, spaceBefore=6 * mm,
            spaceAfter=3 * mm, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=15, textColor=TEAL, spaceBefore=4 * mm,
            spaceAfter=2 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.2, leading=13.2, textColor=INK, spaceAfter=2.4 * mm,
        ),
        "abstract": ParagraphStyle(
            "Abstract", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.5, leading=14, textColor=INK, backColor=PALE,
            borderColor=TEAL, borderWidth=0.8, borderPadding=9,
            spaceAfter=4 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=12.8, leftIndent=5 * mm, firstLineIndent=-3.5 * mm,
            bulletIndent=0, textColor=INK, spaceAfter=1.4 * mm,
        ),
        "code": ParagraphStyle(
            "Code", parent=base["Code"], fontName="Courier", fontSize=7.6,
            leading=10.5, leftIndent=4 * mm, rightIndent=4 * mm,
            backColor=colors.HexColor("#F4F6F8"), borderPadding=6,
            borderColor=GRID, borderWidth=0.5, spaceAfter=3 * mm,
        ),
        "caption": ParagraphStyle(
            "Caption", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=7.6, leading=10, textColor=MUTED, alignment=TA_CENTER,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.7, leading=10.5, textColor=MUTED,
        ),
        "table_header": ParagraphStyle(
            "TableHeader", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.7, leading=10.5, textColor=colors.white,
        ),
    }


def header_footer(canvas, document) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
    canvas.setFont("Helvetica-Bold", 7.6)
    canvas.setFillColor(NAVY)
    canvas.drawString(18 * mm, height - 11 * mm, "WHEN AGENTS CONTROL THE KERNEL, REVISITED")
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - 18 * mm, height - 11 * mm, "TECHNICAL RESEARCH NOTE v0.1")
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.drawString(18 * mm, 8.5 * mm, "FerrumOS OS-JEPA v3.4 - simulation evidence - not deployed")
    canvas.drawRightString(width - 18 * mm, 8.5 * mm, f"{document.page}")
    canvas.restoreState()


def parse_table(lines: list[str], available_width: float, s: dict) -> Table:
    rows = []
    for row_index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        style = s["table_header"] if not rows else s["small"]
        rows.append([Paragraph(inline(cell), style) for cell in cells])
    columns = len(rows[0])
    if columns == 4:
        widths = [available_width * 0.18, available_width * 0.34, available_width * 0.31, available_width * 0.17]
    elif columns == 6:
        widths = [available_width * 0.30] + [available_width * 0.10] * 4 + [available_width * 0.20]
    else:
        widths = [available_width / columns] * columns
    table = Table(rows, colWidths=widths, repeatRows=1, splitByRow=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.45, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build(source: Path, output: Path) -> None:
    s = styles()
    lines = source.read_text(encoding="utf-8").splitlines()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=21 * mm, bottomMargin=18 * mm,
        title="When Agents Control the Kernel, Revisited",
        author="Vyom Kulshrestha",
        subject="OS-JEPA v3.4 request-bounded authority research note",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=header_footer)])
    story = [
        Spacer(1, 23 * mm),
        Paragraph("When Agents Control the Kernel, Revisited", s["title"]),
        Paragraph("Request-Bounded Deterministic Authority with an Action-Conditioned JEPA Forecast", s["subtitle"]),
        Table([["", ""]], colWidths=[18 * mm, doc.width - 18 * mm], rowHeights=[2.2 * mm], style=[
            ("BACKGROUND", (0, 0), (0, 0), ORANGE),
            ("BACKGROUND", (1, 0), (1, 0), TEAL),
        ]),
        Spacer(1, 12 * mm),
        Paragraph("Technical Research Note v0.1 - 26 August 2026", s["meta"]),
        Spacer(1, 3 * mm),
        Paragraph("<b>Vyom Kulshrestha</b><br/>Independent Researcher, India<br/>ORCID: 0009-0009-1434-7148", s["meta"]),
        Spacer(1, 16 * mm),
        Paragraph(
            "Evidence status: source-held-out deterministic software simulation and an untouched-corpus rollout comparison. "
            "The candidate is archived but not deployed; runtime and authority gates remain pending.",
            s["abstract"],
        ),
        Spacer(1, 14 * mm),
        Paragraph("Published lineage", s["h2"]),
        Paragraph(
            "Report DOI 10.5281/zenodo.21829808<br/>Dataset DOI 10.5281/zenodo.21829193<br/>Repository github.com/VyomKulshrestha/Ferrum-OS",
            s["meta"],
        ),
        PageBreak(),
        Spacer(1, 4 * mm),
    ]

    index = next(i for i, line in enumerate(lines) if line == "### Abstract")
    lines = lines[index:]
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(value.strip() for value in paragraph)
        style = s["abstract"] if story and isinstance(story[-1], Paragraph) and getattr(story[-1], "text", "") == "Abstract" else s["body"]
        story.append(Paragraph(inline(text), style))
        paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Paragraph("<br/>".join(escape(value) for value in code_lines), s["code"]))
                code_lines.clear()
            in_code = not in_code
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if line.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            story.extend([parse_table(table_lines, doc.width, s), Spacer(1, 3 * mm)])
            continue
        if not line.strip():
            flush_paragraph()
            i += 1
            continue
        if line.startswith("### "):
            flush_paragraph()
            title = line[4:]
            if title.startswith("7. Limitations"):
                story.append(PageBreak())
            story.append(Paragraph(inline(title), s["h1"]))
        elif line.startswith("#### "):
            flush_paragraph()
            story.append(Paragraph(inline(line[5:]), s["h2"]))
        elif re.match(r"^\d+\. ", line):
            flush_paragraph()
            number, text = line.split(". ", 1)
            story.append(Paragraph(inline(text), s["bullet"], bulletText=f"{number}."))
        elif line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), s["bullet"], bulletText="-"))
        else:
            paragraph.append(line)
        i += 1
    flush_paragraph()
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.source, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
