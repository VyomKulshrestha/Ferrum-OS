#!/usr/bin/env python3
"""Render the Physical JEPA research manuscript to a submission-style PDF."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "research" / "paper" / "learned_caution_deterministic_authority.md"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "paper" / "learned_caution_deterministic_authority_v1.0.pdf"
DEFAULT_RUNNING_HEADER = "LEARNED CAUTION, DETERMINISTIC AUTHORITY - SUBMISSION CANDIDATE v1.0"


def inline(text: str) -> str:
    placeholders: list[str] = []

    def preserve(value: str) -> str:
        placeholders.append(value)
        return f"@@{len(placeholders) - 1}@@"

    text = re.sub(r"`([^`]+)`", lambda match: preserve(f'<font name="Courier">{html.escape(match.group(1))}</font>'), text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: preserve(
            f'<link href="{html.escape(match.group(2), quote=True)}" color="#315f88">{html.escape(match.group(1))}</link>'
        ),
        text,
    )
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    for index, value in enumerate(placeholders):
        text = text.replace(f"@@{index}@@", value)
    return text


def styles():
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PaperTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=27,
            textColor=colors.HexColor("#17202a"),
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "PaperSubtitle",
            parent=sample["Heading2"],
            fontName="Helvetica",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#44546a"),
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "author": ParagraphStyle(
            "PaperAuthor",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#586575"),
            spaceAfter=5,
        ),
        "h1": ParagraphStyle(
            "Section",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=colors.HexColor("#1f496e"),
            spaceBefore=14,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Subsection",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#2d5f78"),
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName="Times-Roman",
            fontSize=9.5,
            leading=13.2,
            alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#20262e"),
            spaceAfter=6,
            allowWidows=0,
            allowOrphans=0,
        ),
        "list": ParagraphStyle(
            "ListBody",
            parent=sample["BodyText"],
            fontName="Times-Roman",
            fontSize=9.5,
            leading=13.2,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#20262e"),
            spaceAfter=4,
        ),
        "abstract": ParagraphStyle(
            "Abstract",
            parent=sample["BodyText"],
            fontName="Times-Italic",
            fontSize=9.4,
            leading=13.2,
            alignment=TA_JUSTIFY,
            borderColor=colors.HexColor("#a9b9c8"),
            borderWidth=0.6,
            borderPadding=8,
            backColor=colors.HexColor("#f5f8fa"),
            spaceAfter=10,
        ),
        "quote": ParagraphStyle(
            "Quote",
            parent=sample["BodyText"],
            fontName="Times-Italic",
            fontSize=10,
            leading=14,
            leftIndent=18,
            rightIndent=18,
            textColor=colors.HexColor("#34495e"),
            borderColor=colors.HexColor("#557a95"),
            borderWidth=0,
            borderPadding=6,
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=sample["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10.5,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#536273"),
            spaceAfter=9,
        ),
        "reference": ParagraphStyle(
            "Reference",
            parent=sample["BodyText"],
            fontName="Times-Roman",
            fontSize=8.5,
            leading=11.5,
            leftIndent=12,
            firstLineIndent=-12,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
    }


def table_flowable(lines: list[str], width: float):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [rows[0], *rows[2:]]
    column_count = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (column_count - len(row)))
    data = [[Paragraph(inline(cell), ParagraphStyle("Cell", fontName="Helvetica", fontSize=7.3, leading=9)) for cell in row] for row in rows]
    first_width = min(2.25 * inch, width * 0.34)
    remaining = (width - first_width) / max(1, column_count - 1)
    table = Table(data, colWidths=[first_width] + [remaining] * (column_count - 1), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244d68")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c5d0d9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def parse(source: Path, document_width: float, status_line: str | None = None):
    style = styles()
    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    index = 0
    in_abstract = False
    in_references = False
    title_seen = False
    subtitle_seen = False
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("!["):
            match = re.match(r"!\[([^]]*)\]\(([^)]+)\)", line)
            if match:
                image_path = (source.parent / match.group(2)).resolve()
                image = Image(str(image_path))
                image._restrictSize(document_width, 4.4 * inch)
                story.extend([Spacer(1, 4), image, Spacer(1, 3)])
            index += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), style["title"]))
            title_seen = True
            index += 1
            continue
        if line.startswith("## ") and title_seen and not subtitle_seen:
            story.append(Paragraph(inline(line[3:]), style["subtitle"]))
            story.append(HRFlowable(width="62%", thickness=0.8, color=colors.HexColor("#6f8da4"), spaceBefore=2, spaceAfter=12))
            subtitle_seen = True
            index += 1
            continue
        if line.startswith("### "):
            heading = line[4:]
            in_abstract = heading == "Abstract"
            in_references = heading == "References"
            story.append(Paragraph(inline(heading), style["h1"]))
            index += 1
            continue
        if line.startswith("#### "):
            story.append(Paragraph(inline(line[5:]), style["h2"]))
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and set(lines[index + 1].replace("|", "").replace(":", "").replace("-", "").strip()) == set():
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.extend([Spacer(1, 4), table_flowable(table_lines, document_width), Spacer(1, 8)])
            continue
        if re.match(r"^\d+\. ", line):
            items = []
            while index < len(lines) and re.match(r"^\d+\. ", lines[index].strip()):
                item_text = re.sub(r"^\d+\. ", "", lines[index].strip())
                items.append(ListItem(Paragraph(inline(item_text), style["list"]), leftIndent=12))
                index += 1
            story.append(ListFlowable(items, bulletType="1", leftIndent=20, bulletFontName="Helvetica", bulletFontSize=8.5))
            story.append(Spacer(1, 4))
            continue
        if line.startswith("> "):
            story.append(Paragraph(inline(line[2:]), style["quote"]))
            index += 1
            continue
        if line.startswith(
            (
                "Anonymous authors",
                "Vyom Kulshrestha",
                "Independent Researcher,",
                "github.com/VyomKulshrestha/",
                "Draft v",
                "Submission candidate v",
            )
        ):
            if status_line is not None and line.startswith(("Draft v", "Submission candidate v")):
                line = status_line
            story.append(Paragraph(inline(line), style["author"]))
            if line.startswith("Draft v"):
                story.append(Spacer(1, 10))
            index += 1
            continue
        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate or candidate.startswith(("#", "|", "![", "> ")) or re.match(r"^\d+\. ", candidate):
                break
            paragraph_lines.append(candidate)
            index += 1
        text = " ".join(paragraph_lines)
        if text.startswith("Figure "):
            paragraph_style = style["caption"]
        elif in_abstract:
            paragraph_style = style["abstract"]
            in_abstract = False
        elif in_references or re.match(r"^\[\d+\]", text):
            paragraph_style = style["reference"]
        else:
            paragraph_style = style["body"]
        story.append(Paragraph(inline(text), paragraph_style))
    return story


def page(canvas, document):
    canvas.saveState()
    width, height = letter
    canvas.setStrokeColor(colors.HexColor("#d4dde4"))
    canvas.setLineWidth(0.4)
    canvas.line(document.leftMargin, height - 0.48 * inch, width - document.rightMargin, height - 0.48 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#667788"))
    canvas.drawString(document.leftMargin, height - 0.38 * inch, document.running_header)
    canvas.drawRightString(width - document.rightMargin, 0.38 * inch, str(document.page))
    canvas.restoreState()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--running-header", default=DEFAULT_RUNNING_HEADER)
    parser.add_argument("--status-line")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(args.output),
        pagesize=letter,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.76 * inch,
        bottomMargin=0.62 * inch,
        title="Learned Caution, Deterministic Authority",
        author="Vyom Kulshrestha",
        subject="Calibration-first runtime boundary for action-conditioned latent world models",
    )
    document.running_header = args.running_header
    story = parse(args.source, document.width, args.status_line)
    document.build(story, onFirstPage=page, onLaterPages=page)
    print(args.output)


if __name__ == "__main__":
    main()
