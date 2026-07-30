"""PDF audit report generation (Milestone 8, +Visual section in Milestone 11). Builds a ReportLab PDF from an AuditResult."""

from __future__ import annotations

import base64
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from models.schemas import AuditResult, CategoryResult, Recommendation, Severity, StructuredAuditReport

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}
_SEVERITY_COLOR = {
    Severity.CRITICAL: colors.HexColor("#b91c1c"),
    Severity.HIGH: colors.HexColor("#c2410c"),
    Severity.MEDIUM: colors.HexColor("#a16207"),
    Severity.LOW: colors.HexColor("#4b5563"),
    Severity.INFO: colors.HexColor("#6b7280"),
}


def _score_color(score: float | None) -> colors.Color:
    if score is None:
        return colors.HexColor("#6b7280")
    if score >= 90:
        return colors.HexColor("#15803d")
    if score >= 50:
        return colors.HexColor("#a16207")
    return colors.HexColor("#b91c1c")


def _fmt_score(score: float | None) -> str:
    return "N/A" if score is None else f"{score:.0f}/100"


def build_pdf_report(
    url: str,
    result: AuditResult,
    performance: CategoryResult | None = None,
    visual: CategoryResult | None = None,
    screenshot_viewport_base64: str | None = None,
) -> bytes:
    """Render an AuditResult (plus optional Performance/Visual results) as a PDF and return its bytes."""
    categories: list[tuple[str, CategoryResult | None]] = [
        ("Accessibility", result.accessibility),
        ("SEO", result.seo),
        ("Copy", result.copy),
        ("Performance", performance),
        ("Visual", visual),
    ]
    return _build_pdf_bytes(url, result.overall_score, categories, screenshot_viewport_base64)


def build_pdf_report_from_structured(url: str, report: StructuredAuditReport) -> bytes:
    """Render today's StructuredAuditReport (all five agents already combined, as returned by
    GET /report/jobs/{id} once a job completes) as a PDF. Shares all the same flowable-building
    logic as build_pdf_report() above — this just adapts the newer, unified report shape instead
    of the legacy pre-Milestone-9 AuditResult + separately-passed performance/visual."""
    categories: list[tuple[str, CategoryResult | None]] = [
        ("Accessibility", report.accessibility),
        ("SEO", report.seo),
        ("Copy", report.copy),
        ("Performance", report.performance),
        ("Visual", report.visual),
    ]
    return _build_pdf_bytes(url, report.summary.overall_score, categories, report.screenshot_viewport_base64)


def _build_pdf_bytes(
    url: str,
    overall_score: float | None,
    categories: list[tuple[str, CategoryResult | None]],
    screenshot_viewport_base64: str | None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("SectionHeading", parent=styles["Heading2"], spaceBefore=16, spaceAfter=6))
    styles.add(ParagraphStyle("ScoreLine", parent=styles["Normal"], fontSize=12, spaceAfter=6))

    story = []
    story.append(Paragraph("AuditPilot Report", styles["Title"]))
    story.append(Paragraph(url, styles["Normal"]))
    story.append(Paragraph(datetime.now(timezone.utc).strftime("Generated %Y-%m-%d %H:%M UTC"), styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    # Executive Summary
    story.append(Paragraph("Executive Summary", styles["Heading1"]))
    story.append(Paragraph(
        f"Overall Score: <font color='#{_score_color(overall_score).hexval()[2:]}'>"
        f"<b>{_fmt_score(overall_score)}</b></font>",
        styles["ScoreLine"],
    ))
    summary_rows = [["Category", "Score", "Summary"]]
    for name, cat in categories:
        if cat is None:
            summary_rows.append([name, "N/A", "Not run"])
        else:
            summary_rows.append([name, _fmt_score(cat.score), cat.summary or "—"])
    summary_table = Table(summary_rows, colWidths=[1.3 * inch, 0.8 * inch, 3.9 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(summary_table)

    # Per-category sections
    for name, cat in categories:
        story.append(Paragraph(name, styles["SectionHeading"]))
        if cat is None:
            story.append(Paragraph("This category was not included in the audit.", styles["Normal"]))
            continue
        story.append(Paragraph(f"Score: <b>{_fmt_score(cat.score)}</b>", styles["Normal"]))
        if cat.summary:
            story.append(Paragraph(cat.summary, styles["Normal"]))

        if name == "Visual":
            story.extend(_screenshot_flowables(screenshot_viewport_base64))
            story.extend(_insight_section_flowables(cat, styles))
        elif name == "Copy":
            story.extend(_insight_section_flowables(cat, styles))
        else:
            story.extend(_recommendation_flowables(cat.recommendations, styles, empty_text="No issues found."))

    # Consolidated Recommendations
    story.append(Paragraph("Recommendations", styles["SectionHeading"]))
    all_recs: list[Recommendation] = []
    for _, cat in categories:
        if cat is not None:
            all_recs.extend(cat.recommendations)
    all_recs.sort(key=lambda r: _SEVERITY_RANK.get(r.severity, 99))
    story.extend(_recommendation_flowables(all_recs, styles, empty_text="No recommendations — everything looks good."))

    doc.build(story)
    return buffer.getvalue()


def _recommendation_flowables(recommendations: list[Recommendation], styles, *, empty_text: str) -> list:
    if not recommendations:
        return [Paragraph(empty_text, styles["Normal"])]

    items = []
    for rec in recommendations:
        color = _SEVERITY_COLOR.get(rec.severity, colors.black).hexval()[2:]
        text = (
            f"<font color='#{color}'><b>[{rec.severity.value.upper()}]</b></font> "
            f"<b>{rec.title}</b> — {rec.description}"
        )
        items.append(ListItem(Paragraph(text, styles["Normal"]), spaceBefore=3))
    return [ListFlowable(items, bulletType="bullet", leftIndent=14)]


def _insight_section_flowables(cat: CategoryResult, styles) -> list:
    """Renders a strengths/weaknesses/recommendations section — shared by Copy and Visual,
    since both agents return the same {strengths, weaknesses, recommendations, score} shape."""
    raw = cat.raw_data or {}
    strengths = raw.get("strengths") or []
    weaknesses = raw.get("weaknesses") or []
    flowables = []
    for label, insights in (("Strengths", strengths), ("Weaknesses", weaknesses)):
        flowables.append(Paragraph(f"<b>{label}</b>", styles["Normal"]))
        if not insights:
            flowables.append(Paragraph("None noted.", styles["Normal"]))
            continue
        items = [
            ListItem(Paragraph(f"<i>{i.get('dimension', '')}</i> — {i.get('point', '')}", styles["Normal"]))
            for i in insights
        ]
        flowables.append(ListFlowable(items, bulletType="bullet", leftIndent=14))
    flowables.append(Paragraph("<b>Recommendations</b>", styles["Normal"]))
    flowables.extend(_recommendation_flowables(cat.recommendations, styles, empty_text="None noted."))
    return flowables


def _screenshot_flowables(screenshot_base64: str | None) -> list:
    """Embeds the above-the-fold viewport screenshot (bounded ~1280x900, so it always
    fits comfortably on one page), scaled to fit the page width. Silently skipped if
    no screenshot was provided or the bytes can't be decoded as an image."""
    if not screenshot_base64:
        return []
    try:
        png_bytes = base64.b64decode(screenshot_base64)
        img = Image(io.BytesIO(png_bytes))
        max_width = 5.5 * inch
        if img.imageWidth:
            scale = min(1.0, max_width / img.imageWidth)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
        return [img, Spacer(1, 0.15 * inch)]
    except Exception:  # noqa: BLE001 - a bad/undecodable image should never break PDF generation
        return []
