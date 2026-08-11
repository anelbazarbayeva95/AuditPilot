"""Branded PDF audit report generation (Milestone 8, +Visual section in Milestone 11, redesigned
for brand/detail/professionalism). Builds a ReportLab PDF from an AuditResult or the newer
StructuredAuditReport.

Visual language is lifted from the dashboard rather than invented: colors and fonts come from
pdf_theme.py (itself sourced from frontend/src/index.css), and the two charts come from
pdf_charts.py (same data ChartsSection.tsx renders, just as static PNGs matplotlib can produce
server-side). Findings are grouped by title the same way the dashboard's GroupedFindingsSection
does, so e.g. 8 empty-button findings render as one evidence-rich card instead of 8 near-identical
ones — "more detailed" means real per-occurrence evidence, not more repetition.

Every finding's evidence block only ever shows values the backend actually captured (context,
selector, section) — same "no fabrication" rule as the rest of the app (see CLAUDE.md). There is
no fallback text-parsing heuristic here the way the frontend's resolveAffectedElement() has for
recommendations with no structured context; a finding with no context/selector simply omits the
evidence block rather than guessing one from the description.
"""

from __future__ import annotations

import base64
import io
import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

import pdf_theme as theme
from models.schemas import AuditResult, CategoryResult, Recommendation, Severity, StructuredAuditReport
from pdf_charts import render_category_score_chart, render_severity_donut_chart

theme.register_fonts()

PAGE_WIDTH, PAGE_HEIGHT = letter
MARGIN = 0.75 * inch
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
BOTTOM_MARGIN = 0.9 * inch
TOP_MARGIN_FIRST = 1.85 * inch
TOP_MARGIN_LATER = 0.85 * inch

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_CATEGORY_LABELS = {
    "accessibility": "Accessibility",
    "seo": "SEO",
    "performance": "Performance",
    "copy": "Copy",
    "visual": "Visual",
}

# Same heuristic as frontend/src/lib/issueText.ts's looksLikeCode() — a selector, a CSS
# combinator, or a raw metric reads better in monospace than as a quoted phrase.
_CODE_PREFIX_RE = re.compile(r"^[.#]")
_COMBINATOR_RE = re.compile(r" > ")
_METRIC_RE = re.compile(r"^-?[\d,]+(\.\d+)?\s?(ms|px|%|s)?$", re.IGNORECASE)


def _looks_like_code(value: str) -> bool:
    trimmed = value.strip()
    return bool(_CODE_PREFIX_RE.match(trimmed) or _COMBINATOR_RE.search(trimmed) or _METRIC_RE.match(trimmed))


def _escape(text: str) -> str:
    return _xml_escape(text or "")


def _hexval(color) -> str:
    return color.hexval()[2:]


# ---------------------------------------------------------------------------
# Public entry points — signatures unchanged so callers in main.py don't move.
# ---------------------------------------------------------------------------

def build_pdf_report(
    url: str,
    result: AuditResult,
    performance: CategoryResult | None = None,
    visual: CategoryResult | None = None,
    screenshot_viewport_base64: str | None = None,
) -> bytes:
    """Render an AuditResult (plus optional Performance/Visual results) as a PDF and return its bytes."""
    categories: list[tuple[str, CategoryResult | None]] = [
        ("accessibility", result.accessibility),
        ("seo", result.seo),
        ("copy", result.copy),
        ("performance", performance),
        ("visual", visual),
    ]
    category_scores = {key: cat.score if cat else None for key, cat in categories}
    all_recs = [rec for _, cat in categories if cat for rec in cat.recommendations]
    issue_counts = _count_by_severity(all_recs)
    return _build_pdf_bytes(url, result.overall_score, categories, category_scores, issue_counts, screenshot_viewport_base64)


def build_pdf_report_from_structured(url: str, report: StructuredAuditReport) -> bytes:
    """Render today's StructuredAuditReport (all five agents already combined, as returned by
    GET /report/jobs/{id} once a job completes) as a PDF. Shares all the same flowable-building
    logic as build_pdf_report() above — this just adapts the newer, unified report shape instead
    of the legacy pre-Milestone-9 AuditResult + separately-passed performance/visual."""
    categories: list[tuple[str, CategoryResult | None]] = [
        ("accessibility", report.accessibility),
        ("seo", report.seo),
        ("copy", report.copy),
        ("performance", report.performance),
        ("visual", report.visual),
    ]
    return _build_pdf_bytes(
        url,
        report.summary.overall_score,
        categories,
        report.summary.category_scores,
        report.summary.issue_counts,
        report.screenshot_viewport_base64,
    )


def _count_by_severity(recommendations: list[Recommendation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in recommendations:
        counts[rec.severity.value] = counts.get(rec.severity.value, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def _build_pdf_bytes(
    url: str,
    overall_score: float | None,
    categories: list[tuple[str, CategoryResult | None]],
    category_scores: dict[str, float | None],
    issue_counts: dict[str, int],
    screenshot_viewport_base64: str | None,
) -> bytes:
    styles = _styles()
    buffer = io.BytesIO()
    generated_at = datetime.now(timezone.utc)

    doc = BaseDocTemplate(
        buffer, pagesize=letter,
        title="AuditPilot Report", author="AuditPilot",
        topMargin=TOP_MARGIN_FIRST, bottomMargin=BOTTOM_MARGIN, leftMargin=MARGIN, rightMargin=MARGIN,
    )
    first_frame = Frame(
        MARGIN, BOTTOM_MARGIN, CONTENT_WIDTH, PAGE_HEIGHT - TOP_MARGIN_FIRST - BOTTOM_MARGIN,
        id="first", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0,
    )
    later_frame = Frame(
        MARGIN, BOTTOM_MARGIN, CONTENT_WIDTH, PAGE_HEIGHT - TOP_MARGIN_LATER - BOTTOM_MARGIN,
        id="later", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0,
    )
    draw_header, draw_footer = _page_decorators(url, generated_at)
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[first_frame], onPage=draw_header),
        PageTemplate(id="Later", frames=[later_frame], onPage=draw_footer),
    ])

    story: list = [NextPageTemplate("Later")]
    story.extend(_executive_summary_flowables(overall_score, category_scores, categories, styles))
    for key, cat in categories:
        story.extend(
            _category_section_flowables(
                key, cat, styles, screenshot_viewport_base64 if key == "visual" else None
            )
        )
    story.extend(_action_list_flowables(categories, issue_counts, styles))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


class _NumberedCanvas(pdfcanvas.Canvas):
    """Defers 'Page N of Total' to save()-time, once the total page count is actually known —
    the standard ReportLab two-pass recipe for page-of-total footers."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_page_number(self, total_pages: int) -> None:
        self.setFont(theme.BODY, 8)
        self.setFillColor(theme.MUTED_FG)
        self.drawRightString(PAGE_WIDTH - MARGIN, 0.55 * inch, f"Page {self._pageNumber} of {total_pages}")


def _page_decorators(url: str, generated_at: datetime):
    def draw_footer(c, _doc):
        c.saveState()
        c.setStrokeColor(theme.BORDER)
        c.setLineWidth(0.6)
        c.line(MARGIN, 0.72 * inch, PAGE_WIDTH - MARGIN, 0.72 * inch)
        mark_font_size = 9
        c.setFont(theme.DISPLAY_BOLD, mark_font_size)
        c.setFillColor(theme.INK)
        c.drawString(MARGIN, 0.53 * inch, "AuditPilot")
        mark_width = c.stringWidth("AuditPilot", theme.DISPLAY_BOLD, mark_font_size)
        c.setFont(theme.BODY, 7.5)
        c.setFillColor(theme.MUTED_FG)
        c.drawString(MARGIN + mark_width + 10, 0.555 * inch, "Automated website audit report")
        c.restoreState()

    def draw_header(c, doc):
        c.saveState()
        c.setFillColor(theme.CREAM)
        c.rect(0, PAGE_HEIGHT - TOP_MARGIN_FIRST + 0.28 * inch, PAGE_WIDTH, TOP_MARGIN_FIRST - 0.28 * inch, stroke=0, fill=1)
        c.setFillColor(theme.LIME)
        c.rect(0, PAGE_HEIGHT - TOP_MARGIN_FIRST + 0.24 * inch, PAGE_WIDTH, 0.04 * inch, stroke=0, fill=1)

        c.setFont(theme.DISPLAY_EXTRABOLD, 23)
        c.setFillColor(theme.INK)
        c.drawString(MARGIN, PAGE_HEIGHT - 0.75 * inch, "AuditPilot")

        c.setFont(theme.BODY_MEDIUM, 9.5)
        c.setFillColor(theme.MUTED_FG)
        c.drawString(MARGIN, PAGE_HEIGHT - 0.98 * inch, "WEBSITE AUDIT REPORT")

        c.setFont(theme.BODY_SEMIBOLD, 11)
        c.setFillColor(theme.INK)
        c.drawString(MARGIN, PAGE_HEIGHT - 1.28 * inch, _truncate(url, 78))

        c.setFont(theme.BODY, 8.5)
        c.setFillColor(theme.MUTED_FG)
        c.drawRightString(PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 0.75 * inch, generated_at.strftime("Generated %B %d, %Y"))
        c.drawRightString(PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 0.90 * inch, generated_at.strftime("%H:%M UTC"))
        c.restoreState()
        draw_footer(c, doc)

    return draw_header, draw_footer


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    return {
        "section_heading": ParagraphStyle(
            "SectionHeading", fontName=theme.DISPLAY_BOLD, fontSize=16, leading=20,
            textColor=theme.INK, spaceBefore=20, spaceAfter=6,
        ),
        "section_summary": ParagraphStyle(
            "SectionSummary", fontName=theme.BODY, fontSize=9.5, leading=13.5,
            textColor=theme.MUTED_FG, spaceAfter=10,
        ),
        "body": ParagraphStyle("Body", fontName=theme.BODY, fontSize=9.5, leading=14, textColor=theme.INK),
        "body_muted": ParagraphStyle("BodyMuted", fontName=theme.BODY, fontSize=9, leading=13, textColor=theme.MUTED_FG),
        "meta": ParagraphStyle("Meta", fontName=theme.BODY_SEMIBOLD, fontSize=7.5, leading=11, textColor=theme.MUTED_FG),
        "finding_title": ParagraphStyle(
            "FindingTitle", fontName=theme.BODY_BOLD, fontSize=11.5, leading=14.5,
            textColor=theme.INK, spaceBefore=3, spaceAfter=3,
        ),
        "evidence_label": ParagraphStyle(
            "EvidenceLabel", fontName=theme.BODY_SEMIBOLD, fontSize=7.5, leading=10, textColor=theme.MUTED_FG,
        ),
        "evidence_quote": ParagraphStyle(
            "EvidenceQuote", fontName=theme.DISPLAY_SEMIBOLD, fontSize=11.5, leading=15, textColor=theme.INK,
        ),
        "evidence_mono": ParagraphStyle(
            "EvidenceMono", fontName=theme.MONO, fontSize=8.5, leading=12.5, textColor=theme.INK,
        ),
        "ai_label": ParagraphStyle("AiLabel", fontName=theme.BODY_SEMIBOLD, fontSize=7.5, leading=10, textColor=theme.QUICKFIX_TEXT),
        "ai_text": ParagraphStyle("AiText", fontName=theme.BODY, fontSize=9, leading=13, textColor=theme.QUICKFIX_TEXT, spaceBefore=2),
        "ai_disclaimer": ParagraphStyle("AiDisclaimer", fontName=theme.BODY, fontSize=7.5, leading=10, textColor=theme.MUTED_FG, spaceBefore=3),
        "table_header": ParagraphStyle("TableHeader", fontName=theme.BODY_BOLD, fontSize=8.5, leading=11, textColor=theme.CREAM),
        "table_cell": ParagraphStyle("TableCell", fontName=theme.BODY, fontSize=8.5, leading=12, textColor=theme.INK),
        "table_cell_bold": ParagraphStyle("TableCellBold", fontName=theme.BODY_BOLD, fontSize=8.5, leading=12, textColor=theme.INK),
        "empty": ParagraphStyle("Empty", fontName=theme.BODY, fontSize=9.5, leading=13, textColor=theme.MUTED_FG),
        "chip_count": ParagraphStyle("ChipCount", fontName=theme.DISPLAY_BOLD, fontSize=15, leading=18, alignment=1),
        "chip_label": ParagraphStyle("ChipLabel", fontName=theme.BODY_MEDIUM, fontSize=7, leading=9, alignment=1),
    }


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

def _executive_summary_flowables(overall_score, category_scores, categories, styles) -> list:
    flow = [Paragraph("Executive Summary", styles["section_heading"])]
    flow.append(_overall_score_row(overall_score, category_scores, styles))
    flow.append(Spacer(1, 14))

    chart_png = render_category_score_chart(category_scores)
    chart_img = Image(io.BytesIO(chart_png))
    scale = CONTENT_WIDTH / chart_img.imageWidth
    chart_img.drawWidth = CONTENT_WIDTH
    chart_img.drawHeight = chart_img.imageHeight * scale
    flow.append(chart_img)
    flow.append(Spacer(1, 10))

    flow.append(_category_score_table(category_scores, categories, styles))
    return flow


def _overall_score_row(overall_score, category_scores, styles) -> Table:
    band_text_color, _, band_label = theme.score_band(overall_score)
    on_dark_color = theme.score_band_on_dark(overall_score)
    score_str = "N/A" if overall_score is None else f"{overall_score:.0f}"

    number_style = ParagraphStyle(
        "ScoreNumber", fontName=theme.DISPLAY_EXTRABOLD, fontSize=44, leading=48, textColor=on_dark_color, alignment=1,
    )
    suffix_style = ParagraphStyle(
        "ScoreSuffix", fontName=theme.BODY_MEDIUM, fontSize=10.5, leading=14, textColor=theme.INK_MUTED, alignment=1,
    )
    band_style = ParagraphStyle(
        "ScoreBandLabel", fontName=theme.BODY_SEMIBOLD, fontSize=10.5, leading=14, textColor=on_dark_color,
        alignment=1, spaceBefore=4,
    )

    # Three short, unbreakable strings on their own lines rather than one Paragraph mixing font
    # sizes inline — mixed-size inline markup wrapped unpredictably at narrow tile widths.
    score_cell = Table(
        [[Paragraph(score_str, number_style)], [Paragraph("out of 100", suffix_style)], [Paragraph(band_label, band_style)]],
        colWidths=[1.9 * inch],
    )
    score_cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme.INK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 18),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
        ("TOPPADDING", (0, 2), (-1, 2), 4),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 16),
    ]))

    counted = [(key, score) for key, score in category_scores.items()]
    chips = []
    for key, score in counted:
        text_color, bar_color, label = theme.score_band(score)
        score_text = "—" if score is None else f"{score:.0f}"
        chip_style = ParagraphStyle("ChipScore", fontName=theme.BODY_BOLD, fontSize=13, leading=16, textColor=text_color, alignment=1)
        name_style = ParagraphStyle("ChipName", fontName=theme.BODY_MEDIUM, fontSize=7.5, leading=10, textColor=theme.MUTED_FG, alignment=1)
        chip = Table(
            [[Paragraph(score_text, chip_style)], [Paragraph(_CATEGORY_LABELS.get(key, key.title()), name_style)]],
            colWidths=[(CONTENT_WIDTH - 2.1 * inch) / max(len(counted), 1)],
        )
        chip.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), theme.MUTED_BG),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        chips.append(chip)

    chips_row = Table([chips], colWidths=[(CONTENT_WIDTH - 2.1 * inch) / max(len(chips), 1)] * len(chips))
    chips_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    outer = Table([[score_cell, Spacer(0.2 * inch, 0), chips_row]], colWidths=[1.9 * inch, 0.2 * inch, CONTENT_WIDTH - 2.1 * inch])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def _category_score_table(category_scores, categories, styles) -> Table:
    summaries = {key: (cat.summary if cat else "Not run") for key, cat in categories}
    rows = [[
        Paragraph("Category", styles["table_header"]),
        Paragraph("Score", styles["table_header"]),
        Paragraph("Summary", styles["table_header"]),
    ]]
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), theme.INK),
        ("BOX", (0, 0), (-1, -1), 0.6, theme.BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, theme.BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for i, (key, score) in enumerate(category_scores.items(), start=1):
        text_color, _, _ = theme.score_band(score)
        score_style = ParagraphStyle("ScoreCell", parent=styles["table_cell_bold"], textColor=text_color)
        rows.append([
            Paragraph(_CATEGORY_LABELS.get(key, key.title()), styles["table_cell_bold"]),
            Paragraph("N/A" if score is None else f"{score:.0f}/100", score_style),
            Paragraph(_escape(summaries.get(key) or "—"), styles["table_cell"]),
        ])
        if i % 2 == 0:
            row_styles.append(("BACKGROUND", (0, i), (-1, i), theme.MUTED_BG))
    table = Table(rows, colWidths=[1.3 * inch, 0.85 * inch, CONTENT_WIDTH - 2.15 * inch])
    table.setStyle(TableStyle(row_styles))
    return table


# ---------------------------------------------------------------------------
# Per-category sections
# ---------------------------------------------------------------------------

def _category_section_flowables(key: str, cat: CategoryResult | None, styles, screenshot_b64: str | None) -> list:
    label = _CATEGORY_LABELS.get(key, key.title())
    flow: list = [Paragraph(label, styles["section_heading"])]

    if cat is None:
        flow.append(Paragraph("This category was not included in the audit.", styles["empty"]))
        return flow

    text_color, _, band_label = theme.score_band(cat.score)
    score_text = "N/A" if cat.score is None else f"{cat.score:.0f}/100"
    score_style = ParagraphStyle("CatScore", fontName=theme.BODY_BOLD, fontSize=11, leading=14, textColor=text_color, spaceAfter=6)
    flow.append(Paragraph(f"{score_text} &nbsp;·&nbsp; {band_label}", score_style))

    if cat.summary:
        flow.append(Paragraph(_escape(cat.summary), styles["section_summary"]))

    if key == "visual" and screenshot_b64:
        shot = _screenshot_flowable(screenshot_b64)
        if shot:
            flow.append(shot)
            flow.append(Spacer(1, 10))

    if key in ("copy", "visual"):
        flow.extend(_insight_flowables(cat, styles))
    else:
        flow.extend(_finding_flowables(cat.recommendations, styles, empty_text="No issues found — nice and clean."))
    return flow


def _insight_flowables(cat: CategoryResult, styles) -> list:
    """Strengths/weaknesses/recommendations — shared shape returned by Copy and Visual."""
    raw = cat.raw_data or {}
    flow: list = []
    for label, insights, heading_color in (
        ("Strengths", raw.get("strengths") or [], theme.STATUS_GOOD),
        ("Areas to improve", raw.get("weaknesses") or [], theme.STATUS_NEEDS_WORK),
    ):
        heading_style = ParagraphStyle(
            f"Insight{label}", fontName=theme.BODY_BOLD, fontSize=10, leading=13,
            textColor=heading_color, spaceBefore=8, spaceAfter=3,
        )
        flow.append(Paragraph(label, heading_style))
        if not insights:
            flow.append(Paragraph("None noted.", styles["body_muted"]))
            continue
        items = [
            ListItem(Paragraph(
                f"<b>{_escape(item.get('dimension', ''))}</b> — {_escape(item.get('point', ''))}", styles["body"]
            ))
            for item in insights
        ]
        flow.append(ListFlowable(items, bulletType="bullet", leftIndent=14))

    recs_heading = ParagraphStyle(
        "InsightRecs", fontName=theme.BODY_BOLD, fontSize=10, leading=13, textColor=theme.INK, spaceBefore=10, spaceAfter=3,
    )
    flow.append(Paragraph("Recommendations", recs_heading))
    flow.extend(_finding_flowables(cat.recommendations, styles, empty_text="None noted."))
    return flow


def _screenshot_flowable(screenshot_base64: str) -> Table | None:
    """Embeds the above-the-fold viewport screenshot in a bordered frame. Silently skipped if
    no screenshot was provided or the bytes can't be decoded as an image."""
    try:
        png_bytes = base64.b64decode(screenshot_base64)
        img = Image(io.BytesIO(png_bytes))
        max_width = CONTENT_WIDTH - 0.16 * inch
        if img.imageWidth:
            scale = min(1.0, max_width / img.imageWidth)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
        framed = Table([[img]], colWidths=[img.drawWidth + 0.16 * inch])
        framed.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, theme.BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return framed
    except Exception:  # noqa: BLE001 - a bad/undecodable image should never break PDF generation
        return None


# ---------------------------------------------------------------------------
# Findings — grouped by title (mirrors GroupedFindingsSection/groupFindingsByTitle), rendered
# as evidence-first cards (mirrors IssueItem.tsx's stripe + Detected block + description shape).
# ---------------------------------------------------------------------------

def _group_by_title(recommendations: list[Recommendation]) -> list[list[Recommendation]]:
    order: list[str] = []
    groups: dict[str, list[Recommendation]] = {}
    for rec in recommendations:
        if rec.title not in groups:
            groups[rec.title] = []
            order.append(rec.title)
        groups[rec.title].append(rec)
    return [groups[title] for title in order]


def _finding_flowables(recommendations: list[Recommendation], styles, *, empty_text: str, show_category_tag: bool = False) -> list:
    if not recommendations:
        return [Paragraph(empty_text, styles["empty"])]
    flow: list = []
    for group in _group_by_title(recommendations):
        flow.append(KeepTogether([_finding_card(group, styles, show_category_tag=show_category_tag), Spacer(1, 8)]))
    return flow


def _finding_card(group: list[Recommendation], styles, *, show_category_tag: bool) -> Table:
    primary = group[0]
    severity_key = primary.severity.value
    stripe_color = theme.SEVERITY_COLORS.get(severity_key, theme.MUTED_FG)
    chip_text_color = theme.SEVERITY_TEXT_ON_CHIP.get(severity_key, theme.INK)
    elevated = severity_key in ("critical", "high")

    meta_bits = [f"<font color='#{_hexval(chip_text_color)}' backColor='#{_hexval(stripe_color)}'>&nbsp;{severity_key.upper()}&nbsp;</font>"]
    if show_category_tag:
        meta_bits.append(_escape(primary.category.value.upper()))
    if primary.section:
        meta_bits.append(_escape(primary.section))
    if len(group) > 1:
        meta_bits.append(f"<b>× {len(group)} occurrences</b>")
    content: list = [Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(meta_bits), styles["meta"])]
    content.append(Paragraph(_escape(primary.title), styles["finding_title"]))

    evidence = _evidence_block(group, styles)
    if evidence:
        content.append(evidence)

    content.append(Paragraph(_escape(primary.description), styles["body"]))

    ai_suggestion = next((rec.ai_suggestion for rec in group if rec.ai_suggestion), None)
    if ai_suggestion:
        content.append(_ai_suggestion_block(ai_suggestion, styles))

    inner_width = CONTENT_WIDTH - 0.34 * inch
    card = Table([[content]], colWidths=[inner_width])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme.ELEVATED_BG if elevated else theme.CARD),
        ("BOX", (0, 0), (-1, -1), 0.6, theme.BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3, stripe_color),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def _evidence_block(group: list[Recommendation], styles) -> Table | None:
    values: list[str] = []
    seen: set[str] = set()
    for rec in group:
        value = (rec.context or rec.selector or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    if not values:
        return None

    section = next((rec.section for rec in group if rec.section), None)
    label_text = "DETECTED" if len(values) == 1 else f"DETECTED ({len(values)})"
    label_line = f"{label_text}&nbsp;&nbsp;&nbsp;{_escape(section)}" if section else label_text
    rows: list = [Paragraph(label_line, styles["evidence_label"])]

    shown, overflow = values[:6], values[6:]
    for value in shown:
        style = styles["evidence_mono"] if _looks_like_code(value) else styles["evidence_quote"]
        text = _escape(value) if _looks_like_code(value) else f"“{_escape(value)}”"
        rows.append(Paragraph(text, style))
    if overflow:
        rows.append(Paragraph(f"+ {len(overflow)} more", styles["body_muted"]))

    inner_width = CONTENT_WIDTH - 0.34 * inch - 0.32 * inch
    box = Table([[rows]], colWidths=[inner_width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme.MUTED_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return box


def _ai_suggestion_block(suggestion: str, styles) -> Table:
    inner_width = CONTENT_WIDTH - 0.34 * inch - 0.32 * inch
    box = Table([[[
        Paragraph("AI SUGGESTION", styles["ai_label"]),
        Paragraph(_escape(suggestion), styles["ai_text"]),
        Paragraph(
            "Generated by Gemini from this page's real content — review before using; "
            "it's a suggestion, not a verified fact.",
            styles["ai_disclaimer"],
        ),
    ]]], colWidths=[inner_width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme.QUICKFIX_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
    ]))
    return box


# ---------------------------------------------------------------------------
# Consolidated action list
# ---------------------------------------------------------------------------

def _action_list_flowables(categories: list[tuple[str, CategoryResult | None]], issue_counts: dict[str, int], styles) -> list:
    flow: list = [Paragraph("Action List", styles["section_heading"])]
    flow.append(Paragraph(
        "Every recommendation across all five categories, prioritized by severity.",
        styles["section_summary"],
    ))

    donut_png = render_severity_donut_chart(issue_counts)
    if donut_png:
        donut_img = Image(io.BytesIO(donut_png))
        max_width = 3.4 * inch
        scale = min(1.0, max_width / donut_img.imageWidth)
        donut_img.drawWidth = donut_img.imageWidth * scale
        donut_img.drawHeight = donut_img.imageHeight * scale
        flow.append(donut_img)
        flow.append(Spacer(1, 6))

    all_recs: list[Recommendation] = []
    for _, cat in categories:
        if cat is not None:
            all_recs.extend(cat.recommendations)
    all_recs.sort(key=lambda rec: _SEVERITY_RANK.get(rec.severity, 99))

    flow.extend(_finding_flowables(
        all_recs, styles, empty_text="No recommendations — everything looks good.", show_category_tag=True
    ))
    return flow
