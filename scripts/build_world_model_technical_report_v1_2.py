#!/usr/bin/env python3
"""Build the full FerrumOS world-model Technical Report v1.2 PDF."""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re

from PIL import Image as PILImage
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "research" / "paper" / "when_agents_control_kernel_technical_report_v1_2.md"
DEFAULT_OUTPUT = ROOT / "output" / "pdf" / "FerrumOS_WorldModel_Technical_Report_v1.2.pdf"

INK = colors.HexColor("#172334")
MUTED = colors.HexColor("#526276")
NAVY = colors.HexColor("#143550")
TEAL = colors.HexColor("#16777A")
ORANGE = colors.HexColor("#D97941")
PALE = colors.HexColor("#EEF4F6")
GRID = colors.HexColor("#C7D3DC")
WHITE = colors.white

# Keep document IDs and timestamps stable so the frozen PDF is reproducible.
rl_config.invariant = True


def inline(text: str) -> str:
    value = escape(text.strip())
    value = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", value)
    value = re.sub(
        r"(?<!href=')(https?://[^\s&lt;]+)",
        r"<link href='\1' color='#16777A'>\1</link>",
        value,
    )
    return value


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "front_eyebrow": ParagraphStyle(
            "FrontEyebrow", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=8.8, leading=10.5, textColor=MUTED, alignment=TA_CENTER,
            spaceAfter=2.6 * mm,
        ),
        "front_title": ParagraphStyle(
            "FrontTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20.5, leading=22.2, textColor=NAVY, alignment=TA_LEFT,
            spaceAfter=2.2 * mm,
        ),
        "front_meta": ParagraphStyle(
            "FrontMeta", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.0, leading=8.3, textColor=INK,
        ),
        "front_abstract_heading": ParagraphStyle(
            "FrontAbstractHeading", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=12.2, textColor=TEAL, alignment=TA_CENTER,
            spaceBefore=1.5 * mm, spaceAfter=1.2 * mm,
        ),
        "front_abstract": ParagraphStyle(
            "FrontAbstract", parent=base["BodyText"], fontName="Times-Roman",
            fontSize=7.8, leading=9.65, textColor=INK, alignment=TA_JUSTIFY,
            spaceAfter=1.2 * mm,
        ),
        "front_h1": ParagraphStyle(
            "FrontH1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=13.4, leading=15.2, textColor=NAVY,
            spaceBefore=2.1 * mm, spaceAfter=1.0 * mm, keepWithNext=True,
        ),
        "front_h2": ParagraphStyle(
            "FrontH2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=8.3, leading=9.7, textColor=INK,
            spaceBefore=1.2 * mm, spaceAfter=0.7 * mm, keepWithNext=True,
        ),
        "front_body": ParagraphStyle(
            "FrontBody", parent=base["BodyText"], fontName="Times-Roman",
            fontSize=7.75, leading=9.6, textColor=INK, alignment=TA_JUSTIFY,
            spaceAfter=1.15 * mm,
        ),
        "front_claim_label": ParagraphStyle(
            "FrontClaimLabel", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.0, leading=8.3, textColor=NAVY,
        ),
        "front_claim": ParagraphStyle(
            "FrontClaim", parent=base["BodyText"], fontName="Times-Roman",
            fontSize=7.0, leading=8.3, textColor=INK,
        ),
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=22.5, textColor=NAVY, alignment=TA_LEFT,
            spaceAfter=3.5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Heading2"], fontName="Helvetica",
            fontSize=11.5, leading=14.2, textColor=TEAL, alignment=TA_LEFT,
            spaceAfter=4.5 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.8, leading=10.2, textColor=MUTED, spaceAfter=1.4 * mm,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=13.6, leading=16.3, textColor=NAVY,
            spaceBefore=3.5 * mm, spaceAfter=2.2 * mm, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.2, leading=12.6, textColor=TEAL,
            spaceBefore=2.6 * mm, spaceAfter=1.5 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.1, leading=10.55, textColor=INK, spaceAfter=1.6 * mm,
            splitLongWords=False,
        ),
        "abstract": ParagraphStyle(
            "Abstract", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.9, leading=10.4, textColor=INK, backColor=PALE,
            borderColor=TEAL, borderWidth=0.7, borderPadding=7,
            spaceAfter=2.2 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.9, leading=10.25, leftIndent=4.2 * mm,
            firstLineIndent=-3.2 * mm, bulletIndent=0, textColor=INK,
            spaceAfter=1.0 * mm,
        ),
        "code": ParagraphStyle(
            "Code", parent=base["Code"], fontName="Courier", fontSize=6.6,
            leading=8.6, leftIndent=3 * mm, rightIndent=3 * mm,
            backColor=colors.HexColor("#F5F7F8"), borderPadding=5,
            borderColor=GRID, borderWidth=0.45, spaceAfter=2 * mm,
        ),
        "caption": ParagraphStyle(
            "Caption", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=6.6, leading=8.4, textColor=MUTED, alignment=TA_CENTER,
            spaceAfter=1.8 * mm,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.45, leading=8.2, textColor=INK,
        ),
        "table_header": ParagraphStyle(
            "TableHeader", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=6.25, leading=7.8, textColor=WHITE,
        ),
    }


def draw_header_footer(
    canvas,
    document,
    *,
    running_left: str = "WHEN AGENTS CONTROL THE KERNEL",
    running_right: str = "TECHNICAL REPORT v1.2",
    footer_note: str = "FerrumOS world-model safety gate - evidence frozen 26 August 2026",
) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(17 * mm, height - 14.5 * mm, width - 17 * mm, height - 14.5 * mm)
    canvas.setFont("Helvetica-Bold", 7.1)
    canvas.setFillColor(NAVY)
    canvas.drawString(17 * mm, height - 10.8 * mm, running_left)
    canvas.setFont("Helvetica", 7.1)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - 17 * mm, height - 10.8 * mm, running_right)
    canvas.line(17 * mm, 13 * mm, width - 17 * mm, 13 * mm)
    canvas.drawString(17 * mm, 8.5 * mm, footer_note)
    canvas.drawRightString(width - 17 * mm, 8.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def column_widths(column_count: int, width: float) -> list[float]:
    fractions = {
        2: [0.34, 0.66],
        3: [0.28, 0.28, 0.44],
        4: [0.18, 0.32, 0.31, 0.19],
        5: [0.30, 0.175, 0.175, 0.175, 0.175],
        6: [0.30, 0.14, 0.14, 0.14, 0.14, 0.14],
        7: [0.28] + [0.12] * 6,
        8: [0.26] + [0.1057] * 7,
    }.get(column_count, [1.0 / column_count] * column_count)
    total = sum(fractions)
    return [width * value / total for value in fractions]


def parse_table(lines: list[str], width: float, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Paragraph]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(cell and set(cell) <= {"-", ":"} for cell in cells):
            continue
        paragraph_style = styles["table_header"] if not rows else styles["small"]
        rows.append([Paragraph(inline(cell), paragraph_style) for cell in cells])
    table = Table(
        rows,
        colWidths=column_widths(len(rows[0]), width),
        repeatRows=1,
        splitByRow=1,
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.3),
        ("TOPPADDING", (0, 0), (-1, -1), 3.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
    ]))
    return table


def parse_image(line: str, width: float, styles: dict[str, ParagraphStyle]):
    match = re.fullmatch(r"!\[(.+)\]\((.+)\)", line.strip())
    if not match:
        return None
    caption, raw_path = match.groups()
    path = ROOT / raw_path
    with PILImage.open(path) as source:
        source_width, source_height = source.size
    max_width = width
    max_height = 72 * mm
    scale = min(max_width / source_width, max_height / source_height)
    image = Image(str(path), width=source_width * scale, height=source_height * scale)
    image.hAlign = "CENTER"
    return [image, Spacer(1, 1.2 * mm), Paragraph(inline(caption), styles["caption"])]


def build(
    source: Path,
    output: Path,
    *,
    pdf_title: str = "When Agents Control the Kernel: A JEPA World Model Safety Gate with Empirical False-Negative Decomposition",
    pdf_subject: str = "FerrumOS world-model safety gate Technical Report v1.2",
    pdf_keywords: str = "FerrumOS, JEPA, operating systems, autonomous agents, safety runtime",
    running_left: str = "WHEN AGENTS CONTROL THE KERNEL",
    running_right: str = "TECHNICAL REPORT v1.2",
    footer_note: str = "FerrumOS world-model safety gate - evidence frozen 26 August 2026",
    spacious_body: bool = False,
    compact_body: bool = False,
) -> None:
    styles = make_styles()
    if spacious_body and compact_body:
        raise ValueError("body cannot be both spacious and compact")
    if spacious_body:
        styles["body"].fontSize = 8.65
        styles["body"].leading = 11.35
        styles["body"].spaceAfter = 1.9 * mm
        styles["bullet"].fontSize = 8.4
        styles["bullet"].leading = 11.0
        styles["small"].fontSize = 6.9
        styles["small"].leading = 8.8
        styles["table_header"].fontSize = 6.65
        styles["table_header"].leading = 8.3
        styles["caption"].fontSize = 7.0
        styles["caption"].leading = 8.9
        styles["code"].fontSize = 6.9
        styles["code"].leading = 9.0
    elif compact_body:
        styles["body"].fontSize = 7.8
        styles["body"].leading = 10.0
        styles["body"].spaceAfter = 1.3 * mm
        styles["bullet"].fontSize = 7.65
        styles["bullet"].leading = 9.75
        styles["small"].fontSize = 6.2
        styles["small"].leading = 7.8
        styles["table_header"].fontSize = 6.0
        styles["table_header"].leading = 7.5
        styles["caption"].fontSize = 6.35
        styles["caption"].leading = 8.0
        styles["code"].fontSize = 6.35
        styles["code"].leading = 8.2
    lines = source.read_text(encoding="utf-8").splitlines()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = BaseDocTemplate(
        str(output), pagesize=A4,
        leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=18.5 * mm, bottomMargin=17 * mm,
        title=pdf_title,
        author="Vyom Kulshrestha",
        subject=pdf_subject,
        keywords=pdf_keywords,
    )
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="normal")
    def page_decor(canvas, current_document) -> None:
        draw_header_footer(
            canvas,
            current_document,
            running_left=running_left,
            running_right=running_right,
            footer_note=footer_note,
        )

    document.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_decor)])

    abstract_index = lines.index("### Abstract")
    intro_index = lines.index("### 1. Introduction")
    contributions_index = lines.index("#### 1.1 Contributions")
    boundary_index = lines.index("#### 1.2 Claim boundary")
    front_end = next(
        index for index in range(boundary_index + 1, len(lines))
        if lines[index] == "<!-- PAGE BREAK -->"
    )

    def paragraphs_between(start: int, end: int) -> list[str]:
        values: list[str] = []
        current: list[str] = []
        for value in lines[start:end]:
            if value.strip():
                current.append(value.strip())
            elif current:
                values.append(" ".join(current))
                current.clear()
        if current:
            values.append(" ".join(current))
        return values

    title = lines[0][2:]
    subtitle = lines[2][3:]
    meta = [value for value in lines[4:abstract_index] if value.strip()]
    abstract_paragraphs = paragraphs_between(abstract_index + 1, intro_index)
    intro_paragraphs = paragraphs_between(intro_index + 1, contributions_index)
    contribution_paragraphs = paragraphs_between(contributions_index + 1, boundary_index)
    claim_paragraphs = paragraphs_between(boundary_index + 1, front_end)

    left_meta = "<b>" + inline(meta[1]) + "</b><br/>" + inline(meta[2]) + "<br/>" + inline(meta[3])
    right_meta = (
        inline(meta[0]) + "<br/>" + inline(meta[6]) + "<br/>" +
        inline(meta[5]) + " | " + inline(meta[4])
    )
    meta_table = Table(
        [[Paragraph(left_meta, styles["front_meta"]), Paragraph(right_meta, styles["front_meta"])]],
        colWidths=[document.width * 0.31, document.width * 0.69],
        hAlign="LEFT",
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    claim_table = Table(
        [[
            Paragraph("Claim boundary", styles["front_claim_label"]),
            Paragraph(inline(" ".join(claim_paragraphs)), styles["front_claim"]),
        ]],
        colWidths=[document.width * 0.17, document.width * 0.83],
        hAlign="LEFT",
    )
    claim_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.55, TEAL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [
        Spacer(1, 1.2 * mm),
        Paragraph(inline(subtitle), styles["front_eyebrow"]),
        Paragraph(inline(title), styles["front_title"]),
        meta_table,
        Spacer(1, 1.1 * mm),
        Paragraph("ABSTRACT", styles["front_abstract_heading"]),
    ]
    story.extend(Paragraph(inline(value), styles["front_abstract"]) for value in abstract_paragraphs)
    story.extend([
        Spacer(1, 0.6 * mm),
        claim_table,
        Paragraph("1 Introduction", styles["front_h1"]),
    ])
    story.extend(Paragraph(inline(value), styles["front_body"]) for value in intro_paragraphs)
    story.append(Paragraph("Contributions", styles["front_h2"]))
    story.extend(Paragraph(inline(value), styles["front_body"]) for value in contribution_paragraphs)
    story.extend([PageBreak(), Spacer(1, 1.5 * mm)])

    lines = lines[front_end + 1:]
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    abstract_mode = False

    def flush_paragraph() -> None:
        nonlocal abstract_mode
        if not paragraph:
            return
        text = " ".join(value.strip() for value in paragraph)
        story.append(Paragraph(inline(text), styles["abstract"] if abstract_mode else styles["body"]))
        paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if line == "<!-- PAGE BREAK -->":
            flush_paragraph()
            story.append(PageBreak())
            story.append(Spacer(1, 1.5 * mm))
            abstract_mode = False
            index += 1
            continue
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Paragraph("<br/>".join(escape(value) for value in code_lines), styles["code"]))
                code_lines.clear()
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith("|"):
            flush_paragraph()
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.extend([parse_table(table_lines, document.width, styles), Spacer(1, 1.8 * mm)])
            continue
        image_flowables = parse_image(line, document.width, styles) if line.startswith("![") else None
        if image_flowables:
            flush_paragraph()
            story.extend(image_flowables)
            index += 1
            continue
        if not line.strip():
            flush_paragraph()
            index += 1
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), styles["title"]))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline(line[3:]), styles["subtitle"]))
        elif line.startswith("### "):
            flush_paragraph()
            heading = line[4:]
            abstract_mode = heading == "Abstract"
            story.append(Paragraph(inline(heading), styles["h1"]))
        elif line.startswith("#### "):
            flush_paragraph()
            abstract_mode = False
            story.append(Paragraph(inline(line[5:]), styles["h2"]))
        elif re.match(r"^\d+\. ", line):
            flush_paragraph()
            number, text = line.split(". ", 1)
            story.append(Paragraph(inline(text), styles["bullet"], bulletText=f"{number}."))
        elif line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), styles["bullet"], bulletText="-"))
        elif not any(item.startswith("### ") for item in lines[:index]) and not line.startswith("Published lineage:"):
            flush_paragraph()
            story.append(Paragraph(inline(line), styles["meta"]))
        elif line.startswith("Published lineage:"):
            flush_paragraph()
            story.append(Paragraph(inline(line), styles["meta"]))
            story.append(Table([["", ""]], colWidths=[18 * mm, document.width - 18 * mm], rowHeights=[1.6 * mm], style=[
                ("BACKGROUND", (0, 0), (0, 0), ORANGE),
                ("BACKGROUND", (1, 0), (1, 0), TEAL),
            ]))
            story.append(Spacer(1, 2.3 * mm))
        else:
            paragraph.append(line)
        index += 1
    flush_paragraph()
    document.build(story)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.source, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
