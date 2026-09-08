#!/usr/bin/env python3
"""Build the full FerrumOS world-model Technical Report v1.2 PDF."""

from __future__ import annotations

import argparse
from functools import partial
from html import escape
from pathlib import Path
import re

from PIL import Image as PILImage
import reportlab
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT
    / "docs"
    / "research"
    / "paper"
    / "when_agents_control_kernel_technical_report_v1_2.md"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "pdf" / "FerrumOS_WorldModel_Technical_Report_v1.2.pdf"
)

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


def register_embedded_fonts() -> None:
    """Register the redistributable TrueType family bundled with ReportLab."""

    font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    font_files = {
        "ReportSans": "Vera.ttf",
        "ReportSans-Bold": "VeraBd.ttf",
        "ReportSans-Italic": "VeraIt.ttf",
        "ReportSans-BoldItalic": "VeraBI.ttf",
        "ReportCode": "Vera.ttf",
    }
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in font_files.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily(
        "ReportSans",
        normal="ReportSans",
        bold="ReportSans-Bold",
        italic="ReportSans-Italic",
        boldItalic="ReportSans-BoldItalic",
    )
    # Prevent the canvas from registering an unused, unembedded Base-14 font
    # before the first flowable is drawn.
    rl_config.canvas_basefontname = "ReportSans"


def inline(text: str) -> str:
    # Base-14 fonts render these punctuation glyphs inconsistently across PDF
    # viewers. Normalize to an ASCII archival text path before markup parsing.
    normalized = (
        text.strip()
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )
    value = escape(normalized)
    value = re.sub(r"`([^`]+)`", r"<font name='ReportCode'>\1</font>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", value)
    value = re.sub(
        r"(?<!href=')(https?://[^\s&lt;]+)",
        r"<link href='\1' color='#16777A'>\1</link>",
        value,
    )
    return value


def split_for_readability(text: str, limit: int = 780) -> list[str]:
    """Split long prose at sentence boundaries without changing its wording."""

    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    paragraphs: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*current, sentence])
        if current and len(candidate) > limit:
            paragraphs.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


class EvidenceChain(Flowable):
    """Compact vector centerpiece for the report's six evidence objects."""

    labels = (
        ("PREDICTION",),
        ("COUNTER-", "FACTUAL"),
        ("WARNING",),
        ("INTERVENTION",),
        ("OUTCOME",),
        ("AUTHORITY",),
    )

    def __init__(self, width: float):
        super().__init__()
        self.width = width
        self.height = 29 * mm

    def wrap(self, available_width, available_height):
        return min(self.width, available_width), self.height

    def draw(self):
        canvas = self.canv
        width = self.width
        gap = 4.2 * mm
        box_width = (width - gap * 5) / 6
        box_height = 10.5 * mm
        y = 10.2 * mm
        fills = (TEAL, NAVY, NAVY, NAVY, ORANGE, TEAL)

        canvas.saveState()
        canvas.setFont("ReportSans-Bold", 7.0)
        canvas.setFillColor(NAVY)
        canvas.drawString(0, 25.2 * mm, "SIX DISTINCT EVIDENCE OBJECTS")
        for index, (label_lines, fill) in enumerate(zip(self.labels, fills)):
            x = index * (box_width + gap)
            canvas.setFillColor(fill)
            canvas.roundRect(x, y, box_width, box_height, 2.2 * mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("ReportSans-Bold", 6.3 if index == 3 else 6.6)
            if len(label_lines) == 1:
                canvas.drawCentredString(x + box_width / 2, y + 4.1 * mm, label_lines[0])
            else:
                canvas.drawCentredString(x + box_width / 2, y + 5.7 * mm, label_lines[0])
                canvas.drawCentredString(x + box_width / 2, y + 2.9 * mm, label_lines[1])
        canvas.setFillColor(MUTED)
        canvas.setFont("ReportSans-Italic", 6.7)
        canvas.drawString(
            0,
            4.2 * mm,
            "Prediction != warning != intervention != outcome != authority",
        )
        canvas.restoreState()


class HazardStepsChart(Flowable):
    """Small horizontal comparison chart for the frozen attribution result."""

    rows = (
        ("Full + JEPA", 129, NAVY),
        ("Local / no JEPA", 132, colors.HexColor("#4E7FAF")),
        ("JEPA-only", 104, TEAL),
        ("Hazard closeness", 144, ORANGE),
    )

    def __init__(self, width: float):
        super().__init__()
        self.width = width
        self.height = 55 * mm

    def wrap(self, available_width, available_height):
        return min(self.width, available_width), self.height

    def draw(self):
        canvas = self.canv
        width = self.width
        height = self.height
        chart_left = 42 * mm
        chart_right = width - 20 * mm
        chart_width = chart_right - chart_left
        row_centers = (33, 25, 17, 9)

        canvas.saveState()
        canvas.setFillColor(PALE)
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.45)
        canvas.roundRect(0, 0, width, height, 2 * mm, fill=1, stroke=1)

        canvas.setFillColor(NAVY)
        canvas.setFont("ReportSans-Bold", 9.2)
        canvas.drawString(5 * mm, 48 * mm, "Hazard steps by frozen risk source")
        canvas.setFillColor(MUTED)
        canvas.setFont("ReportSans", 6.5)
        canvas.drawString(
            5 * mm,
            43.5 * mm,
            "Fresh layouts; lower is fewer realized hazard steps",
        )

        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.35)
        canvas.setDash(1.4, 1.8)
        for tick in (0, 80, 160):
            x = chart_left + chart_width * tick / 160
            canvas.line(x, 6.3 * mm, x, 37.3 * mm)
            canvas.setFillColor(MUTED)
            canvas.setFont("ReportSans", 5.8)
            canvas.drawCentredString(x, 38.8 * mm, str(tick))
        canvas.setDash()

        for (label, value, fill), center in zip(self.rows, row_centers):
            y = center * mm
            canvas.setFillColor(INK)
            canvas.setFont(
                "ReportSans-Bold" if label == "JEPA-only" else "ReportSans",
                6.7,
            )
            canvas.drawRightString(chart_left - 3 * mm, y - 1.2 * mm, label)
            canvas.setFillColor(fill)
            canvas.roundRect(
                chart_left,
                y - 2.25 * mm,
                chart_width * value / 160,
                4.5 * mm,
                1.1 * mm,
                fill=1,
                stroke=0,
            )
            canvas.setFillColor(INK)
            canvas.setFont("ReportSans-Bold", 6.7)
            canvas.drawString(chart_right + 3 * mm, y - 1.2 * mm, str(value))
        canvas.restoreState()


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "front_eyebrow": ParagraphStyle(
            "FrontEyebrow",
            parent=base["BodyText"],
            fontName="ReportSans-Italic",
            fontSize=8.8,
            leading=10.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=2.6 * mm,
        ),
        "front_title": ParagraphStyle(
            "FrontTitle",
            parent=base["Title"],
            fontName="ReportSans-Bold",
            fontSize=20.5,
            leading=22.2,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=2.2 * mm,
        ),
        "front_meta": ParagraphStyle(
            "FrontMeta",
            parent=base["Normal"],
            fontName="ReportSans",
            fontSize=7.0,
            leading=8.3,
            textColor=INK,
        ),
        "front_abstract_heading": ParagraphStyle(
            "FrontAbstractHeading",
            parent=base["Heading2"],
            fontName="ReportSans-Bold",
            fontSize=10.5,
            leading=12.2,
            textColor=TEAL,
            alignment=TA_CENTER,
            spaceBefore=1.5 * mm,
            spaceAfter=1.2 * mm,
        ),
        "front_abstract": ParagraphStyle(
            "FrontAbstract",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.8,
            leading=9.65,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=1.2 * mm,
        ),
        "front_h1": ParagraphStyle(
            "FrontH1",
            parent=base["Heading1"],
            fontName="ReportSans-Bold",
            fontSize=13.4,
            leading=15.2,
            textColor=NAVY,
            spaceBefore=2.1 * mm,
            spaceAfter=1.0 * mm,
            keepWithNext=True,
        ),
        "front_h2": ParagraphStyle(
            "FrontH2",
            parent=base["Heading2"],
            fontName="ReportSans-Bold",
            fontSize=8.3,
            leading=9.7,
            textColor=INK,
            spaceBefore=1.2 * mm,
            spaceAfter=0.7 * mm,
            keepWithNext=True,
        ),
        "front_body": ParagraphStyle(
            "FrontBody",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.75,
            leading=9.6,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=1.15 * mm,
        ),
        "front_claim_label": ParagraphStyle(
            "FrontClaimLabel",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=7.0,
            leading=8.3,
            textColor=NAVY,
        ),
        "front_claim": ParagraphStyle(
            "FrontClaim",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.0,
            leading=8.3,
            textColor=INK,
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="ReportSans-Bold",
            fontSize=20,
            leading=22.5,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=3.5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Heading2"],
            fontName="ReportSans",
            fontSize=11.5,
            leading=14.2,
            textColor=TEAL,
            alignment=TA_LEFT,
            spaceAfter=4.5 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontName="ReportSans",
            fontSize=7.8,
            leading=10.2,
            textColor=MUTED,
            spaceAfter=1.4 * mm,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="ReportSans-Bold",
            fontSize=13.6,
            leading=16.3,
            textColor=NAVY,
            spaceBefore=3.5 * mm,
            spaceAfter=2.2 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="ReportSans-Bold",
            fontSize=10.2,
            leading=12.6,
            textColor=TEAL,
            spaceBefore=2.6 * mm,
            spaceAfter=1.5 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=8.1,
            leading=10.55,
            textColor=INK,
            spaceAfter=1.6 * mm,
            splitLongWords=False,
        ),
        "abstract": ParagraphStyle(
            "Abstract",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.9,
            leading=10.4,
            textColor=INK,
            backColor=PALE,
            borderColor=TEAL,
            borderWidth=0.7,
            borderPadding=7,
            spaceAfter=2.2 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="ReportSans",
            bulletFontName="ReportSans",
            fontSize=7.9,
            leading=10.25,
            leftIndent=4.2 * mm,
            firstLineIndent=-3.2 * mm,
            bulletIndent=0,
            textColor=INK,
            spaceAfter=1.0 * mm,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="ReportCode",
            fontSize=6.6,
            leading=8.6,
            leftIndent=3 * mm,
            rightIndent=3 * mm,
            backColor=colors.HexColor("#F5F7F8"),
            borderPadding=5,
            borderColor=GRID,
            borderWidth=0.45,
            spaceAfter=2 * mm,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=base["BodyText"],
            fontName="ReportSans-Italic",
            fontSize=6.6,
            leading=8.4,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=1.8 * mm,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=6.45,
            leading=8.2,
            textColor=INK,
        ),
        "callout_label": ParagraphStyle(
            "CalloutLabel",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=6.7,
            leading=8.2,
            textColor=TEAL,
            spaceAfter=0.5 * mm,
        ),
        "callout_text": ParagraphStyle(
            "CalloutText",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.4,
            leading=9.4,
            textColor=INK,
        ),
        "result_label": ParagraphStyle(
            "ResultLabel",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=7.0,
            leading=8.5,
            textColor=WHITE,
            spaceAfter=0.7 * mm,
        ),
        "result_text": ParagraphStyle(
            "ResultText",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.5,
            leading=9.4,
            textColor=WHITE,
        ),
        "panel_heading": ParagraphStyle(
            "PanelHeading",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=6.8,
            leading=8.2,
            textColor=WHITE,
        ),
        "panel_label": ParagraphStyle(
            "PanelLabel",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=6.8,
            leading=8.4,
            textColor=TEAL,
            spaceAfter=0.8 * mm,
        ),
        "panel_text": ParagraphStyle(
            "PanelText",
            parent=base["BodyText"],
            fontName="ReportSans",
            fontSize=7.7,
            leading=9.6,
            textColor=INK,
        ),
        "table_note": ParagraphStyle(
            "TableNote",
            parent=base["BodyText"],
            fontName="ReportSans-Italic",
            fontSize=6.1,
            leading=7.7,
            textColor=MUTED,
            leftIndent=1.5 * mm,
            rightIndent=1.5 * mm,
            spaceAfter=1.6 * mm,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName="ReportSans-Bold",
            fontSize=6.25,
            leading=7.8,
            textColor=WHITE,
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
    canvas.setFont("ReportSans-Bold", 7.1)
    canvas.setFillColor(NAVY)
    canvas.drawString(17 * mm, height - 10.8 * mm, running_left)
    canvas.setFont("ReportSans", 7.1)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - 17 * mm, height - 10.8 * mm, running_right)
    canvas.line(17 * mm, 13 * mm, width - 17 * mm, 13 * mm)
    canvas.drawString(17 * mm, 8.5 * mm, footer_note)
    canvas.drawRightString(width - 17 * mm, 8.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def callout_box(
    label: str,
    text: str,
    width: float,
    styles: dict[str, ParagraphStyle],
    *,
    accent=TEAL,
) -> Table:
    content = [
        Paragraph(inline(label.upper()), styles["callout_label"]),
        Paragraph(inline(text), styles["callout_text"]),
    ]
    table = Table(
        [[Paragraph("", styles["callout_text"]), content]],
        colWidths=[2.2 * mm, width - 2.2 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), accent),
                ("BACKGROUND", (1, 0), (1, 0), PALE),
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("BOX", (0, 0), (-1, -1), 0.45, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("TOPPADDING", (0, 0), (0, 0), 0),
                ("BOTTOMPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 7),
                ("RIGHTPADDING", (1, 0), (1, 0), 7),
                ("TOPPADDING", (1, 0), (1, 0), 6),
                ("BOTTOMPADDING", (1, 0), (1, 0), 6),
            ]
        )
    )
    return table


def architecture_result_box(
    width: float, styles: dict[str, ParagraphStyle]
) -> Table:
    cells = [
        [
            Paragraph("PHYSICAL", styles["result_label"]),
            Paragraph("FERRUMOS", styles["result_label"]),
        ],
        [
            Paragraph("JEPA leads all registered horizons", styles["result_text"]),
            Paragraph("Ranking is composition-sensitive", styles["result_text"]),
        ],
    ]
    table = Table(cells, colWidths=[width / 2, width / 2])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), TEAL),
                ("BACKGROUND", (1, 0), (1, -1), NAVY),
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 1),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
                ("LINEBEFORE", (1, 0), (1, -1), 2, WHITE),
            ]
        )
    )
    return table


def research_questions_box(
    width: float, styles: dict[str, ParagraphStyle]
) -> Table:
    cells = [
        [
            Paragraph("RESEARCH QUESTIONS", styles["panel_heading"]),
            Paragraph("", styles["panel_heading"]),
        ],
        [
            [
                Paragraph("RQ1 / PREDICTION", styles["panel_label"]),
                Paragraph(
                    "Does one architecture consistently dominate across domains?",
                    styles["panel_text"],
                ),
            ],
            [
                Paragraph("RQ2 / OPERATIONAL VALUE", styles["panel_label"]),
                Paragraph(
                    "Does predictive quality translate into operational caution?",
                    styles["panel_text"],
                ),
            ],
        ],
    ]
    table = Table(cells, colWidths=[width / 2, width / 2])
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (1, 0), NAVY),
                ("BACKGROUND", (0, 1), (1, 1), PALE),
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("BOX", (0, 0), (-1, -1), 0.45, GRID),
                ("LINEBEFORE", (1, 1), (1, 1), 0.45, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("TOPPADDING", (0, 1), (-1, 1), 7),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ]
        )
    )
    return table


def safety_gym_result_strip(
    width: float, styles: dict[str, ParagraphStyle]
) -> Table:
    cells = [
        [
            [
                Paragraph("PLANNER", styles["result_label"]),
                Paragraph("94.53% completion<br/>70 hazard steps", styles["result_text"]),
            ],
            [
                Paragraph("UNION", styles["result_label"]),
                Paragraph("96.09% completion<br/>84 hazard steps", styles["result_text"]),
            ],
            [
                Paragraph("INTERPRETATION", styles["panel_label"]),
                Paragraph(
                    "Completion +1.56 points; hazard cost +14 steps. Neither paired difference excludes zero.",
                    styles["panel_text"],
                ),
            ],
        ]
    ]
    table = Table(cells, colWidths=[width * 0.22, width * 0.22, width * 0.56])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), NAVY),
                ("BACKGROUND", (1, 0), (1, 0), TEAL),
                ("BACKGROUND", (2, 0), (2, 0), PALE),
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("BOX", (0, 0), (-1, -1), 0.45, GRID),
                ("LINEBEFORE", (1, 0), (-1, 0), 1.2, WHITE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


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


def parse_table(
    lines: list[str], width: float, styles: dict[str, ParagraphStyle]
) -> Table:
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
        splitInRow=0,
        hAlign="LEFT",
    )
    table_style = [
        ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.3),
        ("TOPPADDING", (0, 0), (-1, -1), 3.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
    ]
    table_style.extend(("NOSPLIT", (0, row), (-1, row)) for row in range(len(rows)))
    table.setStyle(TableStyle(table_style))
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
    editorial_layout: bool = False,
) -> None:
    register_embedded_fonts()
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
    if editorial_layout:
        styles["front_abstract"].fontSize = 8.05
        styles["front_abstract"].leading = 10.5
        styles["front_abstract"].spaceAfter = 2.0 * mm
        styles["front_body"].fontSize = 8.0
        styles["front_body"].leading = 10.45
        styles["front_body"].spaceAfter = 1.6 * mm
        styles["body"].fontSize = 7.95
        styles["body"].leading = 10.45
        styles["body"].spaceAfter = 1.55 * mm
        styles["h1"].fontSize = 13.2
        styles["h1"].leading = 15.6
        styles["h1"].spaceBefore = 4.3 * mm
        styles["h1"].spaceAfter = 2.5 * mm
        styles["h1"].backColor = PALE
        styles["h1"].borderColor = GRID
        styles["h1"].borderWidth = 0.45
        styles["h1"].borderPadding = 5
        styles["h2"].spaceBefore = 3.0 * mm
        styles["h2"].spaceAfter = 1.8 * mm
    readable_layout = editorial_layout and spacious_body
    if readable_layout:
        styles["front_eyebrow"].fontSize = 10.2
        styles["front_eyebrow"].leading = 13.0
        styles["front_title"].fontSize = 25.0
        styles["front_title"].leading = 27.5
        styles["front_meta"].fontSize = 8.4
        styles["front_meta"].leading = 10.8
        styles["front_abstract_heading"].fontSize = 14.8
        styles["front_abstract_heading"].leading = 17.5
        styles["front_abstract_heading"].alignment = TA_LEFT
        styles["front_abstract"].fontSize = 9.25
        styles["front_abstract"].leading = 12.6
        styles["front_abstract"].spaceAfter = 2.5 * mm
        styles["front_h1"].fontSize = 15.8
        styles["front_h1"].leading = 18.4
        styles["front_h2"].fontSize = 11.2
        styles["front_h2"].leading = 13.6
        styles["front_body"].fontSize = 9.25
        styles["front_body"].leading = 12.5
        styles["front_body"].spaceAfter = 2.1 * mm
        styles["front_claim_label"].fontSize = 7.8
        styles["front_claim_label"].leading = 9.8
        styles["front_claim"].fontSize = 8.3
        styles["front_claim"].leading = 10.7
        styles["body"].fontSize = 9.25
        styles["body"].leading = 12.45
        styles["body"].spaceAfter = 2.1 * mm
        styles["h1"].fontSize = 15.4
        styles["h1"].leading = 18.0
        styles["h1"].spaceBefore = 5.0 * mm
        styles["h1"].spaceAfter = 3.0 * mm
        styles["h2"].fontSize = 11.4
        styles["h2"].leading = 13.8
        styles["h2"].spaceBefore = 3.8 * mm
        styles["h2"].spaceAfter = 2.2 * mm
        styles["bullet"].fontSize = 9.0
        styles["bullet"].leading = 12.1
        styles["bullet"].spaceAfter = 1.5 * mm
        styles["small"].fontSize = 7.0
        styles["small"].leading = 8.8
        styles["table_header"].fontSize = 6.6
        styles["table_header"].leading = 8.2
        styles["caption"].fontSize = 7.2
        styles["caption"].leading = 9.1
        styles["code"].fontSize = 7.0
        styles["code"].leading = 9.1
    lines = source.read_text(encoding="utf-8").splitlines()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=18.5 * mm,
        bottomMargin=19 * mm,
        title=pdf_title,
        author="Vyom Kulshrestha",
        subject=pdf_subject,
        keywords=pdf_keywords,
    )
    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="normal",
    )

    def page_decor(canvas, current_document) -> None:
        draw_header_footer(
            canvas,
            current_document,
            running_left=running_left,
            running_right=running_right,
            footer_note=footer_note,
        )

    document.addPageTemplates(
        [PageTemplate(id="main", frames=[frame], onPageEnd=page_decor)]
    )

    abstract_index = lines.index("### Abstract")
    intro_index = lines.index("### 1. Introduction")
    contributions_index = lines.index("#### 1.1 Contributions")
    boundary_index = lines.index("#### 1.2 Claim boundary")
    front_end = next(
        index
        for index in range(boundary_index + 1, len(lines))
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
    contribution_paragraphs = paragraphs_between(
        contributions_index + 1, boundary_index
    )
    claim_paragraphs = paragraphs_between(boundary_index + 1, front_end)

    left_meta = (
        "<b>"
        + inline(meta[1])
        + "</b><br/>"
        + inline(meta[2])
        + "<br/>"
        + inline(meta[3])
    )
    right_meta = (
        inline(meta[0])
        + "<br/>"
        + inline(meta[6])
        + "<br/>"
        + inline(meta[5])
        + " | "
        + inline(meta[4])
    )
    meta_table = Table(
        [
            [
                Paragraph(left_meta, styles["front_meta"]),
                Paragraph(right_meta, styles["front_meta"]),
            ]
        ],
        colWidths=[document.width * 0.31, document.width * 0.69],
        hAlign="LEFT",
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    claim_table = Table(
        [
            [
                Paragraph("Claim boundary", styles["front_claim_label"]),
                Paragraph(inline(" ".join(claim_paragraphs)), styles["front_claim"]),
            ]
        ],
        colWidths=[document.width * 0.17, document.width * 0.83],
        hAlign="LEFT",
    )
    claim_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.55, TEAL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    if readable_layout:
        story = [
            Spacer(1, 24 * mm),
            Paragraph(inline(subtitle), styles["front_eyebrow"]),
            Paragraph(inline(title), styles["front_title"]),
            Table(
                [["", ""]],
                colWidths=[18 * mm, document.width - 18 * mm],
                rowHeights=[2.0 * mm],
                style=[
                    ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                    ("BACKGROUND", (0, 0), (0, 0), ORANGE),
                    ("BACKGROUND", (1, 0), (1, 0), TEAL),
                ],
            ),
            Spacer(1, 12 * mm),
            meta_table,
            Spacer(1, 18 * mm),
            callout_box(
                "v1.2 evidence update",
                "Observed Physical JEPA output values are now compared with preregistered development-mean masking on complete retained paired catalogs. The analysis remains retrospective because the prospective v1 execution failed its final protected-file check.",
                document.width,
                styles,
                accent=ORANGE,
            ),
            Spacer(1, 8 * mm),
            EvidenceChain(document.width),
            PageBreak(),
            Spacer(1, 2.0 * mm),
            Paragraph("Abstract", styles["front_abstract_heading"]),
        ]
        story.extend(
            Paragraph(inline(value), styles["front_abstract"])
            for value in abstract_paragraphs
        )
        story.extend([Spacer(1, 2.0 * mm), claim_table])
    else:
        story = [
            Spacer(1, 1.2 * mm),
            Paragraph(inline(subtitle), styles["front_eyebrow"]),
            Paragraph(inline(title), styles["front_title"]),
            meta_table,
            Spacer(1, 1.1 * mm),
            Paragraph("ABSTRACT", styles["front_abstract_heading"]),
        ]
        story.extend(
            Paragraph(inline(value), styles["front_abstract"])
            for value in abstract_paragraphs
        )
    if editorial_layout and not readable_layout:
        story.extend(
            [
                Spacer(1, 1.4 * mm),
                callout_box(
                    "Core finding",
                    "Prediction quality, counterfactual response, warning quality, effective intervention, realized outcome, and independently enforced authority are distinct evidence objects.",
                    document.width,
                    styles,
                ),
                Spacer(1, 4.0 * mm),
                EvidenceChain(document.width),
                PageBreak(),
                Spacer(1, 1.5 * mm),
            ]
        )
    elif not readable_layout:
        story.append(Spacer(1, 0.6 * mm))
    if not readable_layout:
        story.append(claim_table)
    story.append(Paragraph("1 Introduction", styles["front_h1"]))
    story.extend(
        Paragraph(inline(value), styles["front_body"]) for value in intro_paragraphs
    )
    story.append(Paragraph("Contributions", styles["front_h2"]))
    for value in contribution_paragraphs:
        pieces = split_for_readability(value, 620) if editorial_layout else [value]
        story.extend(Paragraph(inline(piece), styles["front_body"]) for piece in pieces)
    if editorial_layout:
        story.extend(
            [
                Spacer(1, 3.5 * mm),
                research_questions_box(document.width, styles),
            ]
        )
    if readable_layout:
        story.append(Spacer(1, 7 * mm))
    else:
        story.extend([PageBreak(), Spacer(1, 1.5 * mm)])

    lines = lines[front_end + 1 :]
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    abstract_mode = False

    def flush_paragraph() -> None:
        nonlocal abstract_mode
        if not paragraph:
            return
        text = " ".join(value.strip() for value in paragraph)
        paragraph_style = styles["abstract"] if abstract_mode else styles["body"]
        pieces = (
            split_for_readability(text)
            if editorial_layout and not abstract_mode
            else [text]
        )
        story.extend(Paragraph(inline(piece), paragraph_style) for piece in pieces)
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
                story.append(
                    Paragraph(
                        "<br/>".join(escape(value) for value in code_lines),
                        styles["code"],
                    )
                )
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
            table_note = None
            if editorial_layout and table_lines[0].startswith(
                "| Component exercised | Test class | Committed pass evidence"
            ):
                table_lines = [
                    "| Component | Test | Evidence | Availability / boundary |",
                    "|---|---|---|---|",
                    "| FerrumOS gate | QEMU integration | `world_model_failure_modes.json`: pass | Command path available; failure modes exercised [a] |",
                    "| Assistant mediation | QEMU observation | `world_model_natural_use_verification_v1.json`: pass | Reads available; writes await confirmation; deletes blocked |",
                    "| Signed neural permit | Host unit | Authority inventory: 9/9 | Protocol only; syscall path not exercised [b] |",
                    "| Physical permit and disabled driver | Host unit | `cross_domain_authority_test_inventory_v1.json`: 128/128 | Simulator/offline adapter only; physical actuator unavailable |",
                    "| Safety-Gym adapter | Host integration | Runtime verification: pass | Simulator commands only; no actuator [c] |",
                ]
                table_note = (
                    "[a] Cases include false-safe, missing, non-finite, and forbidden-coverage artifacts. "
                    "[b] Host-unit protocol coverage does not establish FerrumOS syscall-path enforcement. "
                    "[c] Physical actuator delivery was unavailable or disabled."
                )
            table_group = [
                parse_table(table_lines, document.width, styles),
            ]
            if table_note:
                table_group.append(Paragraph(inline(table_note), styles["table_note"]))
            if editorial_layout and table_lines[0].startswith(
                "| Final arm | Completion |"
            ):
                table_group.extend(
                    [
                        Spacer(1, 2.0 * mm),
                        safety_gym_result_strip(document.width, styles),
                    ]
                )
            if editorial_layout and table_lines[0].startswith(
                "| Risk source | Completion | Effective recall |"
            ):
                table_group.extend(
                    [
                        Spacer(1, 2.2 * mm),
                        HazardStepsChart(document.width),
                    ]
                )
            table_group.append(Spacer(1, 1.8 * mm))
            if len(table_lines) <= 8:
                story.append(KeepTogether(table_group))
            else:
                story.extend(table_group)
            continue
        image_flowables = (
            parse_image(line, document.width, styles) if line.startswith("![") else None
        )
        if image_flowables:
            flush_paragraph()
            if editorial_layout and "matched_rollout_results.png" in line:
                story.extend(
                    [
                        architecture_result_box(document.width, styles),
                        Spacer(1, 2.4 * mm),
                    ]
                )
            if readable_layout:
                story.append(KeepTogether(image_flowables))
            else:
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
            heading = line[5:]
            story.append(Paragraph(inline(heading), styles["h2"]))
            if editorial_layout:
                boundaries = {
                    "4.2 Matched architecture study": (
                        "Evidence boundary",
                        "Matched data, seeds, parameter counts, and update budgets; FLOPs and training wall time are not equalized.",
                    ),
                    "4.3 Aggregation, temporal causality, and uncertainty": (
                        "Evidence boundary",
                        "Episode bootstraps condition on fixed trained checkpoints and do not include retraining variability.",
                    ),
                    "5.2 Interpretation": (
                        "Evidence boundary",
                        "The common-episode comparison is post-hoc; leave-one-out checks are sensitivity analyses, not independent replications.",
                    ),
                }
                if heading in boundaries:
                    label, text = boundaries[heading]
                    story.extend(
                        [
                            callout_box(label, text, document.width, styles),
                            Spacer(1, 1.7 * mm),
                        ]
                    )
        elif re.match(r"^\d+\. ", line):
            flush_paragraph()
            number, text = line.split(". ", 1)
            story.append(
                Paragraph(inline(text), styles["bullet"], bulletText=f"{number}.")
            )
        elif line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(inline(line[2:]), styles["bullet"], bulletText="-"))
        elif not any(
            item.startswith("### ") for item in lines[:index]
        ) and not line.startswith("Published lineage:"):
            flush_paragraph()
            story.append(Paragraph(inline(line), styles["meta"]))
        elif line.startswith("Published lineage:"):
            flush_paragraph()
            story.append(Paragraph(inline(line), styles["meta"]))
            story.append(
                Table(
                    [["", ""]],
                    colWidths=[18 * mm, document.width - 18 * mm],
                    rowHeights=[1.6 * mm],
                    style=[
                        ("FONTNAME", (0, 0), (-1, -1), "ReportSans"),
                        ("BACKGROUND", (0, 0), (0, 0), ORANGE),
                        ("BACKGROUND", (1, 0), (1, 0), TEAL),
                    ],
                )
            )
            story.append(Spacer(1, 2.3 * mm))
        else:
            paragraph.append(line)
        index += 1
    flush_paragraph()
    document.build(story, canvasmaker=partial(Canvas, initialFontName="ReportSans"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.source, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
