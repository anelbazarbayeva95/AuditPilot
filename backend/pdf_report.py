"""PDF audit report generation. Builds a ReportLab PDF from a completed audit.

The structure is deliberate, and it is not the order the data happens to arrive
in: Cover, Executive summary, Scorecard, Priority action plan, Category
findings, Methodology, Appendix. A reader who stops after page two should still
have the result, the risks, and the plan; a reader who wants to check the work
can keep going to the evidence and the conditions it was gathered under.

Three rules run through the whole module:

- Nothing is printed twice. Findings live in their category section; the action
  plan is a ranked, de-duplicated synthesis, not a second copy of the list.
- Machine identifiers never reach prose. Everything user-visible goes through
  labels.humanize(); raw check ids and selectors live in the appendix.
- Measured facts and model judgments are visibly different things. Each finding
  carries how it was detected and how confident that is, because a report that
  presents "LCP is 4820 ms" and "the hero feels unbalanced" in the same voice
  is asking to be trusted on both equally.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    CondPageBreak,
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

from actions import build_action_plan
from labels import format_report_datetime, humanize, pluralize, round_half_up, score_band
from models.schemas import (
    AuditResult,
    CategoryResult,
    DetectionMethod,
    Recommendation,
    ReportSummary,
    RunContext,
    ScoreStatus,
    ScreenshotQuality,
    Severity,
    StructuredAuditReport,
)

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
_TIMING_RANK = {"immediate": 0, "next_sprint": 1, "backlog": 2}
_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}

_INK = colors.HexColor("#111827")
_MUTED = colors.HexColor("#6b7280")
_RULE = colors.HexColor("#d1d5db")
_PANEL = colors.HexColor("#f9fafb")
_WARN_BG = colors.HexColor("#fef3c7")
_WARN_INK = colors.HexColor("#92400e")

_PAGE_WIDTH = 7.0 * inch  # letter minus 0.75in margins each side
_MAX_ACTIONS = 10
_MAX_EXAMPLES_PER_FINDING = 3
_REPORT_TITLE = "Website Audit Report"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_pdf_report(
    url: str,
    result: AuditResult,
    performance: CategoryResult | None = None,
    visual: CategoryResult | None = None,
    screenshot_viewport_base64: str | None = None,
) -> bytes:
    """Render an AuditResult (plus optional Performance/Visual results) as a PDF.

    Legacy shape, kept for direct API callers: there's no run context or
    coverage data on this path, so the Methodology section says what it can and
    is explicit about the rest being unrecorded rather than inventing it.
    """
    categories: list[tuple[str, CategoryResult | None]] = [
        ("Accessibility", result.accessibility),
        ("SEO", result.seo),
        ("Copy", result.copy),
        ("Performance", performance),
        ("Visual", visual),
    ]
    action_plan, kpi_notes = build_action_plan(
        {name.lower(): cat for name, cat in categories if cat is not None}
    )
    view = _ReportView(
        url=url,
        overall_score=result.overall_score,
        categories=categories,
        screenshot_b64=screenshot_viewport_base64,
        action_plan=action_plan,
        kpi_notes=kpi_notes,
    )
    return _build_pdf_bytes(view)


def build_pdf_report_from_structured(url: str, report: StructuredAuditReport) -> bytes:
    """Render a StructuredAuditReport (the current job-based flow) as a PDF."""
    categories = [
        ("Accessibility", report.accessibility),
        ("SEO", report.seo),
        ("Copy", report.copy),
        ("Performance", report.performance),
        ("Visual", report.visual),
    ]
    # combine_report() populates the plan, but a report handed straight to the
    # PDF endpoint (or built before this field existed) may not carry one, and
    # an empty action plan would read as "nothing to do" rather than "not
    # computed". Derive it from the findings instead.
    action_plan, kpi_notes = list(report.action_plan), list(report.kpi_notes)
    if not action_plan:
        action_plan, kpi_notes = build_action_plan(
            {name.lower(): cat for name, cat in categories if cat is not None}
        )

    view = _ReportView(
        url=url,
        overall_score=report.summary.overall_score,
        categories=categories,
        screenshot_b64=report.screenshot_viewport_base64,
        screenshot_quality=report.screenshot_quality,
        run_context=report.run_context,
        summary=report.summary,
        action_plan=action_plan,
        kpi_notes=kpi_notes,
    )
    return _build_pdf_bytes(view)


@dataclass
class _ReportView:
    """Everything the renderer needs, normalized across both entry points."""

    url: str
    overall_score: Optional[float]
    categories: list[tuple[str, Optional[CategoryResult]]]
    screenshot_b64: Optional[str] = None
    screenshot_quality: Optional[ScreenshotQuality] = None
    run_context: Optional[RunContext] = None
    summary: Optional[ReportSummary] = None
    action_plan: list = field(default_factory=list)
    kpi_notes: list[str] = field(default_factory=list)

    @property
    def host(self) -> str:
        parsed = urlparse(self.url)
        return (parsed.netloc or self.url).replace("www.", "")

    @property
    def generated_at(self) -> datetime:
        if self.run_context and self.run_context.finished_at:
            return self.run_context.finished_at
        return datetime.now(timezone.utc)

    def all_recommendations(self) -> list[Recommendation]:
        return [
            rec for _, cat in self.categories if cat is not None for rec in cat.recommendations
        ]


@dataclass
class _Group:
    """One finding, with every element it was observed on.

    Eight buttons with no accessible name are eight real problems and one
    decision, so they're counted honestly and presented once, with examples —
    rather than as eight near-identical bullets a reader learns to skim.
    """

    title: str
    lead: Recommendation
    members: list[Recommendation] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        return len(self.members)


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def _build_pdf_bytes(view: _ReportView) -> bytes:
    buffer = io.BytesIO()
    styles = _build_styles()
    doc = _BookmarkedDoc(
        buffer,
        pagesize=letter,
        topMargin=0.85 * inch, bottomMargin=0.85 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        # Real document metadata. An anonymous, untitled PDF is unusable for
        # document management and hostile to assistive technology — doubly odd
        # for a report that grades other people on accessibility.
        title=f"{_REPORT_TITLE} — {view.host}",
        # Document language, so assistive technology reads the report in the
        # right voice. ReportLab plumbs this through to the PDF catalog's
        # /Lang, and the doc template passes its own value to the canvas — so
        # it has to be set here, not only on the canvas.
        lang="en-US",
        author="AuditPilot",
        subject=f"Automated accessibility, SEO, performance, copy, and visual audit of {view.url}",
        creator="AuditPilot",
        keywords=["website audit", "accessibility", "WCAG", "SEO", "performance", view.host],
    )

    story: list = []
    story += _cover(view, styles)
    story += _executive_summary(view, styles)
    story += _priority_action_plan(view, styles)
    story += _category_sections(view, styles)
    story += _methodology(view, styles)
    story += _appendix(view, styles)

    doc.build(story, canvasmaker=_numbered_canvas_for(view))
    return buffer.getvalue()


class _BookmarkedDoc(SimpleDocTemplate):
    """Adds PDF outline entries for section headings.

    Bookmarks are how anyone navigates a multi-page PDF with a screen reader or
    a sidebar, and they cost one hook.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bookmark_seq = 0

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = {"SectionH1": 0, "SectionH2": 1}.get(flowable.style.name)
        if level is None:
            return
        self._bookmark_seq += 1
        key = f"section-{self._bookmark_seq}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(flowable.getPlainText(), key, level=level, closed=False)


def _numbered_canvas_for(view: _ReportView):
    """Canvas that knows the page count, so footers can say 'Page 2 of 7'.

    ReportLab draws pages as it goes and doesn't know the total until the end,
    so pages are held back and stamped on save. The document language is set
    here too — assistive technology needs it to pick the right voice.
    """
    footer_left = f"{_REPORT_TITLE} — {view.host}"

    class _NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            # The doc template passes lang= explicitly, so a plain setdefault
            # wouldn't catch a None coming through from an older caller.
            kwargs["lang"] = kwargs.get("lang") or "en-US"
            super().__init__(*args, **kwargs)
            self._saved_states: list[dict] = []

        def showPage(self):  # noqa: N802 - reportlab's API casing
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                if self._pageNumber > 1:  # the cover carries no furniture
                    self._draw_footer(total)
                super().showPage()
            super().save()

        def _draw_footer(self, total: int) -> None:
            self.saveState()
            self.setStrokeColor(_RULE)
            self.setLineWidth(0.5)
            self.line(0.75 * inch, 0.65 * inch, letter[0] - 0.75 * inch, 0.65 * inch)
            self.setFont("Helvetica", 8)
            self.setFillColor(_MUTED)
            self.drawString(0.75 * inch, 0.5 * inch, footer_left)
            self.drawRightString(
                letter[0] - 0.75 * inch, 0.5 * inch, f"Page {self._pageNumber} of {total}"
            )
            self.restoreState()

    return _NumberedCanvas


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "CoverTitle", parent=styles["Title"], fontSize=30, leading=34, alignment=0,
        textColor=_INK, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "CoverSubtitle", parent=styles["Normal"], fontSize=14, leading=19, textColor=_MUTED,
        spaceAfter=24,
    ))
    styles.add(ParagraphStyle(
        "SectionH1", parent=styles["Heading1"], fontSize=17, leading=21, textColor=_INK,
        spaceBefore=4, spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        "SectionH2", parent=styles["Heading2"], fontSize=13, leading=17, textColor=_INK,
        spaceBefore=14, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "FindingTitle", parent=styles["Normal"], fontSize=11, leading=14, spaceAfter=3,
    ))
    # Body copy at a comfortable measure — the reviewed report ran long lines
    # edge to edge, which is exactly how dense pages become unreadable.
    styles.add(ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9.5, leading=13.5, spaceAfter=5, textColor=_INK,
    ))
    styles.add(ParagraphStyle(
        "Meta", parent=styles["Normal"], fontSize=8, leading=11, textColor=_MUTED, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        "Mono", parent=styles["Normal"], fontName="Courier", fontSize=7.5, leading=10,
        textColor=_INK, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "Cell", parent=styles["Normal"], fontSize=8.5, leading=11.5, textColor=_INK,
    ))
    styles.add(ParagraphStyle(
        "CellHead", parent=styles["Normal"], fontSize=8.5, leading=11.5,
        fontName="Helvetica-Bold", textColor=_INK,
    ))
    styles.add(ParagraphStyle(
        "ScoreBig", parent=styles["Normal"], fontSize=26, leading=30, alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        "FigureLabel", parent=styles["Normal"], fontSize=9, leading=12, alignment=TA_CENTER,
        textColor=_WARN_INK,
    ))
    return styles


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _cover(view: _ReportView, styles) -> list:
    ctx = view.run_context
    rows = [
        ("Client", view.host),
        ("Audited URL", view.url),
        ("Generated", format_report_datetime(view.generated_at)),
        ("Report version", ctx.report_version if ctx else "1.0"),
        ("Environment", f"Production, {ctx.viewport} desktop viewport" if ctx and ctx.viewport
         else "Production"),
        ("Accessibility target", ctx.wcag_target if ctx else "WCAG 2.2 AA"),
        ("Status", "Automated audit — findings not manually verified"),
    ]
    if ctx and ctx.final_url and ctx.final_url != view.url:
        rows.insert(2, ("Resolved to", ctx.final_url))

    table = Table(
        [[Paragraph(f"<b>{_esc(k)}</b>", styles["Cell"]), Paragraph(_esc(v), styles["Cell"])]
         for k, v in rows],
        colWidths=[1.7 * inch, _PAGE_WIDTH - 1.7 * inch],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _RULE),
    ]))

    return [
        Spacer(1, 1.4 * inch),
        Paragraph(_REPORT_TITLE, styles["CoverTitle"]),
        Paragraph(_esc(view.host), styles["CoverSubtitle"]),
        table,
        Spacer(1, 0.5 * inch),
        Paragraph(
            "Prepared by AuditPilot. Scores, methodology, and scope limitations are documented in "
            "the Methodology section; raw technical output is in the Appendix.",
            styles["Meta"],
        ),
        PageBreak(),
    ]


def _executive_summary(view: _ReportView, styles) -> list:
    story = [Paragraph("Executive summary", styles["SectionH1"])]

    score_text = _fmt_score(view.overall_score)
    color = _score_color(view.overall_score).hexval()[2:]
    # A bare "61/100" leaves the reader to guess whether that's a crisis or a
    # good day. The band label and the scale beneath it make the number mean
    # something without the reader having to infer a convention.
    band = score_band(view.overall_score)
    headline = Table(
        [[
            Paragraph(
                "<b>Overall score</b><br/>"
                + _esc(_overall_verdict(view)),
                styles["Body"],
            ),
            Paragraph(
                f"<font color='#{color}'><b>{score_text}</b></font>"
                + (f"<br/><font size='9' color='#{color}'>{_esc(band)}</font>" if band else ""),
                styles["ScoreBig"],
            ),
        ]],
        colWidths=[_PAGE_WIDTH - 1.8 * inch, 1.8 * inch],
    )
    headline.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(headline)
    story.append(Paragraph(
        "Score bands: 0-39 Critical &nbsp;·&nbsp; 40-69 Needs attention &nbsp;·&nbsp; "
        "70-89 Good &nbsp;·&nbsp; 90-100 Excellent",
        styles["Meta"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.extend(_key_messages(view, styles))

    if view.summary and view.summary.score_explanation:
        story.append(Paragraph(
            f"<b>How this score was calculated:</b> {_esc(view.summary.score_explanation)}",
            styles["Meta"],
        ))
        story.append(Spacer(1, 0.08 * inch))

    story.append(Paragraph("Scorecard", styles["SectionH2"]))
    story.append(_scorecard_table(view, styles))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(
        "Confidence reflects how each category was assessed: automated checks are deterministic "
        "measurements, AI-assisted categories are model judgments. Every category's tested scope "
        "is listed in Methodology.",
        styles["Meta"],
    ))
    return story


def _key_messages(view: _ReportView, styles) -> list:
    """Primary risk, largest opportunity, audit confidence.

    The report's job isn't to report what the scanner found — it's to tell the
    reader what they now know and what to do about it. These three lines are
    the decision; everything after them is the evidence for it. Each is built
    only from measured values, and any message without support is omitted
    rather than padded out.
    """
    messages: list[tuple[str, str]] = []

    top_action = view.action_plan[0] if view.action_plan else None
    if top_action:
        detail = top_action.description
        if top_action.findings_resolved > 1:
            detail = (
                f"{pluralize(top_action.findings_resolved, 'finding')} across "
                f"{', '.join(humanize(c) for c in top_action.categories)} resolve with this one fix."
            )
        messages.append(("Primary risk", f"{top_action.title}. {detail}"))

    saving = _largest_measured_saving(view)
    if saving:
        messages.append(("Largest measured opportunity", saving))

    scored = [name for name, cat in view.categories if cat is not None
              and cat.score_status is ScoreStatus.SCORED]
    excluded = (view.summary.excluded_categories if view.summary else {}) or {}
    confidence = (
        f"{len(scored)} of {len(view.categories)} categories produced reliable evidence."
    )
    if excluded:
        confidence += " " + " ".join(
            f"{humanize(name)} was withheld ({why})." for name, why in excluded.items()
        )
    messages.append(("Audit confidence", confidence))

    rows = [
        [Paragraph(f"<b>{_esc(label)}</b>", styles["Cell"]), Paragraph(_esc(text), styles["Cell"])]
        for label, text in messages
    ]
    table = Table(rows, colWidths=[1.75 * inch, _PAGE_WIDTH - 1.75 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _RULE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.0, _INK),
        ("LEFTPADDING", (0, 0), (0, -1), 9),
    ]))
    return [table, Spacer(1, 0.12 * inch)]


def _largest_measured_saving(view: _ReportView) -> Optional[str]:
    """Total the performance savings Lighthouse actually measured, or say nothing.

    Only quantified savings are claimed — an unquantified "big opportunity" is
    the kind of line that gets an audit disbelieved.
    """
    for name, cat in view.categories:
        if name != "Performance" or cat is None:
            continue
        opportunities = (cat.raw_data or {}).get("opportunities") or []
        total_ms = sum(o.get("savings_ms") or 0 for o in opportunities)
        if not total_ms:
            return None
        named = ", ".join(o.get("title", "") for o in opportunities[:2] if o.get("title"))
        return (
            f"Roughly {total_ms / 1000:.1f}s of measured load-time savings identified"
            + (f", led by: {named}." if named else ".")
        )
    return None


def _overall_verdict(view: _ReportView) -> str:
    """One sentence a reader can act on, built only from what was measured."""
    recs = view.all_recommendations()
    critical = [r for r in recs if r.severity is Severity.CRITICAL]
    high = [r for r in recs if r.severity is Severity.HIGH]
    excluded = list((view.summary.excluded_categories if view.summary else {}).items())

    if not recs:
        sentence = "No issues were found in the checks performed."
    else:
        # Only name the severities actually present — "high or critical" when
        # every one of them is high describes a document the reader isn't
        # holding.
        if critical and high:
            urgency = f"{pluralize(len(critical), 'critical')} and {pluralize(len(high), 'high-severity finding')}"
        elif critical:
            urgency = pluralize(len(critical), 'critical finding')
        elif high:
            urgency = pluralize(len(high), 'high-priority finding')
        else:
            urgency = "no high or critical findings"
        sentence = (
            f"{pluralize(len(recs), 'finding')} across "
            f"{pluralize(len({r.category for r in recs}), 'category', 'categories')}, "
            f"including {urgency}."
        )
    if excluded:
        names = ", ".join(f"{humanize(name)} ({why})" for name, why in excluded)
        sentence += f" Not included in the score: {names}."
    return sentence


def _scorecard_table(view: _ReportView, styles) -> Table:
    """Area / Score / Findings / Confidence / Priority.

    Replaces the old free-text Summary column, which repeated the score and the
    issue count in prose and still overflowed its cell.
    """
    rows = [[
        Paragraph("Area", styles["CellHead"]),
        Paragraph("Score", styles["CellHead"]),
        Paragraph("Findings", styles["CellHead"]),
        Paragraph("Confidence", styles["CellHead"]),
        Paragraph("Priority", styles["CellHead"]),
    ]]

    for name, cat in view.categories:
        if cat is None:
            rows.append([
                Paragraph(_esc(name), styles["Cell"]),
                Paragraph("Not run", styles["Cell"]),
                Paragraph("—", styles["Cell"]),
                Paragraph("—", styles["Cell"]),
                Paragraph("Re-run", styles["Cell"]),
            ])
            continue
        rows.append([
            Paragraph(_esc(name), styles["Cell"]),
            Paragraph(_esc(_score_cell(cat)), styles["Cell"]),
            Paragraph(str(len(cat.recommendations)) if cat.score_status is ScoreStatus.SCORED
                      else "—", styles["Cell"]),
            Paragraph(_esc(_confidence_cell(cat)), styles["Cell"]),
            Paragraph(_esc(_priority_cell(cat)), styles["Cell"]),
        ])

    table = Table(rows, colWidths=[1.5 * inch, 1.15 * inch, 0.8 * inch, 1.65 * inch, 1.9 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _score_cell(cat: CategoryResult) -> str:
    if cat.score_status is ScoreStatus.INSUFFICIENT_EVIDENCE:
        return "Insufficient evidence"
    if cat.score_status is ScoreStatus.NOT_RUN or cat.score is None:
        return "Not run"
    return _fmt_score(cat.score)


def _confidence_cell(cat: CategoryResult) -> str:
    if cat.score_status is not ScoreStatus.SCORED:
        return "—"
    method = cat.coverage.method.value if cat.coverage else None
    if method == "ai_assisted":
        return "Medium — model judgment"
    if method == "automated":
        return "High — automated checks"
    detections = {r.detection for r in cat.recommendations if r.detection}
    if detections == {DetectionMethod.AI_GENERATED}:
        return "Medium — model judgment"
    return "High — automated checks"


def _priority_cell(cat: CategoryResult) -> str:
    if cat.score_status is ScoreStatus.INSUFFICIENT_EVIDENCE:
        return "Re-audit before acting"
    if cat.score_status is ScoreStatus.NOT_RUN:
        return "Re-run"
    if any(r.severity in (Severity.CRITICAL, Severity.HIGH) for r in cat.recommendations):
        return "Immediate"
    if cat.recommendations:
        return "Next sprint"
    return "Maintain"


def _priority_action_plan(view: _ReportView, styles) -> list:
    """The ranked, de-duplicated plan — not a second printing of every finding.

    The reviewed report ended with a "Recommendations" section that repeated
    everything already stated per category, adding length but no decision. This
    replaces it: the same issue flagged by two agents is merged, findings are
    ranked by timing then impact then severity, and only the top items appear —
    detail stays in the category sections.
    """
    story = [
        PageBreak(),
        Paragraph("Priority action plan", styles["SectionH1"]),
    ]

    actions = view.action_plan
    if not actions:
        story.append(Paragraph(
            "No actions arise from the checks performed. See Methodology for tested scope.",
            styles["Body"],
        ))
        return story

    ranked = actions[:_MAX_ACTIONS]
    story.append(Paragraph(
        f"The {pluralize(len(ranked), 'action')} below are ranked by when they should be "
        "scheduled, then by user impact and severity. Each is one unit of work: where a single "
        "fix resolves findings in more than one category, it appears once and names both. Full "
        "detail for every finding is in the category sections that follow.",
        styles["Body"],
    ))
    story.append(Spacer(1, 0.06 * inch))

    rows = [[
        Paragraph("#", styles["CellHead"]),
        Paragraph("Action", styles["CellHead"]),
        Paragraph("Benefits", styles["CellHead"]),
        Paragraph("Impact", styles["CellHead"]),
        Paragraph("Effort", styles["CellHead"]),
        Paragraph("Timing", styles["CellHead"]),
        Paragraph("Owner", styles["CellHead"]),
    ]]
    for index, action in enumerate(ranked, start=1):
        detail = ""
        if action.findings_resolved > 1:
            detail = f"Closes {pluralize(action.findings_resolved, 'finding')}"
        if action.estimated_saving:
            detail = f"{detail} · " if detail else ""
            detail += f"Saves {action.estimated_saving}"
        if action.primary_standard:
            detail = f"{detail}<br/>" if detail else ""
            detail += _esc(action.primary_standard)

        rows.append([
            Paragraph(str(index), styles["Cell"]),
            Paragraph(
                f"<b>{_esc(action.title)}</b>"
                + (f"<br/><font size='7.5' color='#6b7280'>{detail}</font>" if detail else ""),
                styles["Cell"],
            ),
            Paragraph(
                _esc(", ".join(humanize(c) for c in action.categories)), styles["Cell"]
            ),
            Paragraph(_esc(humanize(action.impact)) or "—", styles["Cell"]),
            Paragraph(_esc(humanize(action.effort)) or "—", styles["Cell"]),
            Paragraph(_esc(humanize(action.timing)) or "—", styles["Cell"]),
            Paragraph(_esc(action.owner) if action.owner else "Unassigned", styles["Cell"]),
        ])

    table = Table(
        rows,
        colWidths=[0.28 * inch, 2.5 * inch, 1.15 * inch, 0.72 * inch, 0.7 * inch, 0.85 * inch, 0.8 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.08 * inch))

    # Outcome metrics are named here rather than dropped silently, so their
    # absence from the plan reads as a deliberate distinction between the work
    # and the measure of the work.
    for note in view.kpi_notes:
        story.append(Paragraph(f"<b>Success measure:</b> {_esc(note)}", styles["Meta"]))

    story.append(Paragraph(
        "Owner is only ever populated from information supplied to the audit — AuditPilot does not "
        "infer who maintains a component.",
        styles["Meta"],
    ))
    return story


def _action_sort_key(group: _Group) -> tuple:
    lead = group.lead
    return (
        _TIMING_RANK.get(lead.timing.value if lead.timing else "", 3),
        _IMPACT_RANK.get(lead.impact.value if lead.impact else "", 3),
        _SEVERITY_RANK.get(lead.severity, 9),
        -group.occurrences,
    )


def _category_sections(view: _ReportView, styles) -> list:
    story: list = [PageBreak(), Paragraph("Category findings", styles["SectionH1"])]

    for name, cat in view.categories:
        story.append(Paragraph(_esc(name), styles["SectionH2"]))
        if cat is None:
            story.append(Paragraph("This category was not included in the audit.", styles["Body"]))
            continue

        story.append(Paragraph(
            f"<b>Score:</b> {_esc(_score_cell(cat))}"
            + (f" &nbsp;·&nbsp; <b>Assessment:</b> {_esc(humanize(cat.coverage.method))}"
               if cat.coverage else ""),
            styles["Body"],
        ))
        if cat.summary:
            story.append(Paragraph(_esc(cat.summary), styles["Body"]))
        if cat.score_explanation:
            story.append(Paragraph(
                f"<b>Score derivation:</b> {_esc(cat.score_explanation)}", styles["Meta"]
            ))

        if name == "Visual":
            story.extend(_screenshot_flowables(view, styles))
        if name == "Performance":
            story.extend(_performance_metrics_flowables(cat, styles))
        if name in ("Copy", "Visual"):
            story.extend(_insight_flowables(cat, styles))

        story.extend(_finding_flowables(cat, styles))

    return story


def _finding_flowables(cat: CategoryResult, styles) -> list:
    if not cat.recommendations:
        # "No issues found" is a *result*, and a category that was never
        # assessed doesn't have one. Printing it under a category marked
        # "insufficient evidence" contradicts the disclosure two lines above
        # it and reads as a clean pass.
        if cat.score_status is ScoreStatus.INSUFFICIENT_EVIDENCE:
            return [Paragraph(
                "No findings were generated because the evidence did not meet the quality "
                "threshold for this category. This is not a clean result.",
                styles["Body"],
            )]
        if cat.score_status is ScoreStatus.NOT_RUN:
            return [Paragraph(
                "No findings were generated because this category did not run.", styles["Body"]
            )]
        return [Paragraph("No issues found in this category's checks.", styles["Body"])]

    flowables = [Spacer(1, 0.06 * inch)]
    for group in sorted(_group_recommendations(cat.recommendations), key=_action_sort_key):
        flowables.append(_finding_card(group, styles))
    return flowables


def _finding_card(group: _Group, styles) -> KeepTogether:
    """One finding as a self-contained card: what, where, why, fix, proof.

    Kept together on a page deliberately — a finding split across a page break
    loses its evidence, which is the part that makes it credible.
    """
    lead = group.lead
    severity_color = _SEVERITY_COLOR.get(lead.severity, colors.black).hexval()[2:]

    header = (
        f"<font color='#{severity_color}'><b>{_esc(lead.severity.value.upper())}</b></font> "
        f"&nbsp;<b>{_esc(group.title)}</b>"
    )
    if group.occurrences > 1:
        header += f" <font color='#6b7280'>({pluralize(group.occurrences, 'occurrence')})</font>"

    inner: list = [Paragraph(header, styles["FindingTitle"])]

    tags = [
        f"Detection: {humanize(lead.detection)}" if lead.detection else None,
        f"Confidence: {humanize(lead.confidence)}" if lead.confidence else None,
        f"Impact: {humanize(lead.impact)}" if lead.impact else None,
        f"Effort: {humanize(lead.effort)}" if lead.effort else None,
        f"Timing: {humanize(lead.timing)}" if lead.timing else None,
        lead.wcag_criterion,
    ]
    tag_line = " · ".join(t for t in tags if t)
    if tag_line:
        inner.append(Paragraph(_esc(tag_line), styles["Meta"]))

    inner.append(Paragraph(_esc(lead.description), styles["Body"]))

    # Evidence first — the real detected value, before any explanation of it.
    evidence_rows = _evidence_rows(group)
    if evidence_rows:
        inner.append(Paragraph("<b>Evidence</b>", styles["Meta"]))
        for row in evidence_rows:
            inner.append(Paragraph(row, styles["Mono"]))
        if group.occurrences > len(evidence_rows):
            inner.append(Paragraph(
                f"{group.occurrences - len(evidence_rows)} further occurrences listed in the "
                "Appendix.",
                styles["Meta"],
            ))

    if lead.ai_suggestion:
        inner.append(Paragraph(
            f"<b>Suggested replacement (AI-generated, review before use):</b> "
            f"{_esc(lead.ai_suggestion)}",
            styles["Meta"],
        ))
    if lead.validation:
        inner.append(Paragraph(f"<b>How to validate:</b> {_esc(lead.validation)}", styles["Meta"]))

    card = Table([[inner]], colWidths=[_PAGE_WIDTH])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, _SEVERITY_COLOR.get(lead.severity, _MUTED)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([card, Spacer(1, 0.08 * inch)])


def _evidence_rows(group: _Group) -> list[str]:
    """Up to a few real observed values — DOM excerpt preferred, then location."""
    rows = []
    for member in group.members[:_MAX_EXAMPLES_PER_FINDING]:
        excerpt = member.evidence.dom_excerpt if member.evidence else None
        name_trace = member.evidence.accessible_name_computation if member.evidence else None
        measured = member.evidence.measured_value if member.evidence else None
        threshold = member.evidence.threshold if member.evidence else None

        if measured:
            rows.append(_esc(f"Measured {measured}" + (f" ({threshold})" if threshold else "")))
            continue
        if excerpt:
            where = f"  [{member.section}]" if member.section else ""
            rows.append(_esc(excerpt + where))
        elif member.context:
            where = f"  [{member.section}]" if member.section else ""
            rows.append(_esc(str(member.context) + where))
        elif member.selector:
            rows.append(_esc(member.selector))
        if name_trace:
            rows.append(_esc(f"Accessible name: {name_trace}"))
    return rows


def _performance_metrics_flowables(cat: CategoryResult, styles) -> list:
    """The measured numbers behind the performance score.

    These were always collected and never printed, which is why the reviewed
    report could show 25/100 with no LCP, no CLS, and no conditions anywhere on
    the page.
    """
    raw = cat.raw_data or {}
    metrics = raw.get("metrics") or {}
    if not metrics:
        return []

    definitions = [
        ("Largest Contentful Paint (LCP)", metrics.get("lcp_ms"), "ms", "<= 2500 ms"),
        ("Cumulative Layout Shift (CLS)", metrics.get("cls"), "", "<= 0.1"),
        ("Interaction to Next Paint (INP)", metrics.get("inp_ms"), "ms", "<= 200 ms"),
        ("First Contentful Paint (FCP)", metrics.get("fcp_ms"), "ms", "<= 1800 ms"),
        ("Total Blocking Time (TBT)", metrics.get("tbt_ms"), "ms", "<= 200 ms"),
        ("Speed Index", metrics.get("speed_index_ms"), "ms", "<= 3400 ms"),
    ]
    rows = [[
        Paragraph("Metric", styles["CellHead"]),
        Paragraph("Measured", styles["CellHead"]),
        Paragraph("Good", styles["CellHead"]),
    ]]
    for label, value, unit, good in definitions:
        if value is None:
            continue
        shown = f"{value:.2f}" if unit == "" else f"{value:,.0f} {unit}"
        rows.append([
            Paragraph(_esc(label), styles["Cell"]),
            Paragraph(_esc(shown), styles["Cell"]),
            Paragraph(_esc(good), styles["Cell"]),
        ])
    if len(rows) == 1:
        return []

    table = Table(rows, colWidths=[3.4 * inch, 1.9 * inch, 1.7 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    flowables = [
        Spacer(1, 0.06 * inch),
        Paragraph("<b>Measured metrics</b>", styles["Body"]),
        table,
    ]

    opportunities = raw.get("opportunities") or []
    if opportunities:
        items = []
        for opportunity in opportunities[:5]:
            savings = []
            if opportunity.get("savings_ms"):
                savings.append(f"~{opportunity['savings_ms']:,.0f} ms")
            if opportunity.get("savings_bytes"):
                savings.append(f"{opportunity['savings_bytes'] / 1024:,.0f} KB")
            detail = f" ({', '.join(savings)})" if savings else ""
            resources = opportunity.get("resources") or []
            named = f"<br/><font name='Courier' size='7'>{_esc(', '.join(resources))}</font>" if resources else ""
            items.append(ListItem(Paragraph(
                f"{_esc(opportunity.get('title', ''))}{_esc(detail)}{named}", styles["Body"]
            )))
        flowables += [
            Spacer(1, 0.08 * inch),
            Paragraph("<b>Opportunities measured on this page</b>", styles["Body"]),
            ListFlowable(items, bulletType="bullet", leftIndent=12),
        ]

    flowables.append(Spacer(1, 0.06 * inch))
    return flowables


def _insight_flowables(cat: CategoryResult, styles) -> list:
    """Strengths and weaknesses from an AI-assisted category.

    Labelled as model observations with their stated confidence: "excellent
    contrast" is an opinion, and printing it in the same voice as a measurement
    is how a report overstates what it knows.
    """
    # Empty "Strengths / None noted" headings under a category that was never
    # assessed imply the model looked and found nothing. It didn't look.
    if cat.score_status is not ScoreStatus.SCORED:
        return []

    raw = cat.raw_data or {}
    flowables: list = []
    for label, key in (("Strengths", "strengths"), ("Weaknesses", "weaknesses")):
        insights = raw.get(key) or []
        flowables.append(Paragraph(f"<b>{label}</b>", styles["Body"]))
        if not insights:
            flowables.append(Paragraph("None noted.", styles["Body"]))
            continue
        items = []
        for insight in insights:
            dimension = humanize(insight.get("dimension", ""))
            confidence = insight.get("confidence")
            suffix = (
                f" <font color='#6b7280' size='7.5'>({humanize(confidence)} confidence)</font>"
                if confidence else ""
            )
            items.append(ListItem(Paragraph(
                f"<b>{_esc(dimension)}</b> — {_esc(insight.get('point', ''))}{suffix}",
                styles["Body"],
            )))
        flowables.append(ListFlowable(items, bulletType="bullet", leftIndent=12))
    flowables.append(Spacer(1, 0.06 * inch))
    return flowables


def _screenshot_flowables(view: _ReportView, styles) -> list:
    """The captured render, with a caption — and a disclosure when it failed.

    A screenshot presented without its capture conditions is decoration. A
    *broken* screenshot presented as if it were the page is worse than none at
    all: it contradicts the analysis printed beside it and takes the rest of
    the report's credibility with it. So a degraded capture is labelled as
    evidence of a failed capture, not evidence about the page.
    """
    quality = view.screenshot_quality
    flowables: list = []

    if quality is not None and quality.is_degraded:
        notice = Table(
            [[Paragraph(
                "<b>Incomplete render — not used for assessment.</b><br/>"
                + _esc(quality.reason or "The page did not finish rendering before capture.")
                + "<br/>The screenshot below is shown only to document the failed capture. "
                "Visual analysis was skipped and this category was not scored; re-run the audit "
                "before drawing conclusions about this page's design.",
                styles["Body"],
            )]],
            colWidths=[_PAGE_WIDTH],
        )
        notice.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _WARN_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, _WARN_INK),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        flowables += [Spacer(1, 0.06 * inch), notice, Spacer(1, 0.1 * inch)]

    degraded = quality is not None and quality.is_degraded
    image = _screenshot_image(view.screenshot_b64, max_height=2.6 * inch if degraded else 4.2 * inch)
    if image is None:
        return flowables

    ctx = view.run_context
    caption_bits = [
        f"Viewport {ctx.viewport}" if ctx and ctx.viewport else "Above-the-fold viewport",
        _esc(view.url),
        format_report_datetime(view.generated_at),
    ]
    if quality is not None:
        caption_bits.append(f"Render check: {quality.status}")

    if degraded:
        # A failed capture reproduced bare looks like a rendering defect in
        # *this* document rather than evidence about the audited page. Framing
        # it — labelled, measured, captioned — makes it legible as a diagnostic
        # artefact that was deliberately preserved.
        measurements = []
        if quality.dominant_color_pct is not None:
            measurements.append(f"{quality.dominant_color_pct:.0f}% single flat color")
        if quality.uniform_row_pct is not None:
            measurements.append(f"{quality.uniform_row_pct:.0f}% rows without variation")
        if quality.content_top_pct is not None:
            measurements.append(f"first content at {quality.content_top_pct:.0f}% down")

        figure = Table(
            [
                [Paragraph(
                    "<b>CAPTURE FAILED — NOT ANALYSED</b>", styles["FigureLabel"]
                )],
                [image],
                [Paragraph(
                    _esc("Measured: " + "; ".join(measurements)) if measurements else "",
                    styles["Meta"],
                )],
            ],
            colWidths=[_PAGE_WIDTH],
        )
        figure.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _PANEL),
            ("BACKGROUND", (0, 0), (-1, 0), _WARN_BG),
            ("BOX", (0, 0), (-1, -1), 0.8, _WARN_INK),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, _WARN_INK),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        caption = Paragraph(
            "Figure 1 — The image above is the actual capture, preserved as diagnostic evidence "
            "of the failed render. It is not a rendering fault in this report, and it was not "
            "used to assess the page. " + " · ".join(caption_bits),
            styles["Meta"],
        )
        return flowables + [
            CondPageBreak(3.6 * inch),
            KeepTogether([figure, Spacer(1, 0.05 * inch), caption]),
            Spacer(1, 0.12 * inch),
        ]

    caption = Paragraph(" · ".join(caption_bits), styles["Meta"])
    return flowables + [
        CondPageBreak(3.2 * inch),
        KeepTogether([image, Spacer(1, 0.05 * inch), caption]),
        Spacer(1, 0.12 * inch),
    ]


def _screenshot_image(
    screenshot_base64: Optional[str], max_height: float = 4.2 * inch
) -> Optional[Image]:
    """Decode and size the screenshot, or return None if it can't be used."""
    if not screenshot_base64:
        return None
    try:
        png_bytes = base64.b64decode(screenshot_base64)
        img = Image(io.BytesIO(png_bytes))
        # Wider than the old 5.5in: the reviewed screenshot was too small to
        # inspect while still consuming most of a page.
        max_width = _PAGE_WIDTH - 0.4 * inch
        if img.imageWidth and img.imageHeight:
            scale = min(1.0, max_width / img.imageWidth, max_height / img.imageHeight)
            img.drawWidth = img.imageWidth * scale
            img.drawHeight = img.imageHeight * scale
        return img
    except Exception:  # noqa: BLE001 - a bad image should never break PDF generation
        return None


def _methodology(view: _ReportView, styles) -> list:
    """How the audit ran, what it covered, and what it explicitly did not."""
    story = [
        PageBreak(),
        Paragraph("Methodology", styles["SectionH1"]),
        Paragraph(
            "Every score in this report is produced by the process described here. Conclusions "
            "outside this scope are not supported by this audit.",
            styles["Body"],
        ),
    ]

    ctx = view.run_context
    rows: list[tuple[str, str]] = [("Audited URL", view.url)]
    if ctx:
        rows += [
            ("Resolved URL", ctx.final_url or "Same as requested"),
            ("HTTP status", str(ctx.http_status) if ctx.http_status else "Not recorded"),
            ("Audit started", format_report_datetime(ctx.started_at)),
            ("Audit finished", format_report_datetime(ctx.finished_at) if ctx.finished_at else "—"),
            ("Rendering engine", "Playwright headless Chromium"),
            ("Viewport", ctx.viewport or "Not recorded"),
            ("User agent", ctx.user_agent or "Not recorded"),
            ("Page-load condition", ctx.scraper_wait_until or "Not recorded"),
            ("Accessibility target", ctx.wcag_target),
            ("Report version", ctx.report_version),
        ]
        perf = ctx.performance_run
        if perf:
            rows += [
                ("Lighthouse version", perf.lighthouse_version or "Not recorded"),
                ("Performance form factor", perf.form_factor or "Not recorded"),
                ("Performance throttling", perf.throttling or "Not recorded"),
                ("Screen emulation", perf.screen_emulation or "Not recorded"),
                ("Performance runs", str(perf.runs)),
                ("Measured at", perf.fetch_time or "Not recorded"),
            ]
    else:
        rows.append((
            "Run conditions",
            "Not recorded — this report was generated from a previously computed result without "
            "run context.",
        ))

    table = Table(
        [[Paragraph(f"<b>{_esc(k)}</b>", styles["Cell"]), Paragraph(_esc(v), styles["Cell"])]
         for k, v in rows],
        colWidths=[2.2 * inch, _PAGE_WIDTH - 2.2 * inch],
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    # Scoring model, stated rather than implied.
    story.append(Paragraph("Scoring model", styles["SectionH2"]))
    if view.summary and view.summary.weights:
        weights = ", ".join(
            f"{humanize(name)} {weight:.0%}" for name, weight in view.summary.weights.items()
        )
        story.append(Paragraph(
            f"Categories are weighted by user and business impact: {_esc(weights)}. "
            "Categories without a score are excluded and the remaining weights renormalized.",
            styles["Body"],
        ))
    if view.summary and view.summary.score_explanation:
        story.append(Paragraph(_esc(view.summary.score_explanation), styles["Meta"]))
    story.append(Paragraph(
        "Rule-based categories start at 100 and deduct per finding by severity, with a cap per "
        "check so one repeated issue cannot zero a category on its own. A category containing an "
        "unresolved critical failure is capped at 50. Performance reports Lighthouse's own score, "
        "and the AI-assisted categories report the model's holistic score — neither is "
        "deduction-based, and both are labelled as such.",
        styles["Body"],
    ))

    story.append(Paragraph("Coverage by category", styles["SectionH2"]))
    for name, cat in view.categories:
        if cat is None or cat.coverage is None:
            continue
        story.append(Paragraph(f"<b>{_esc(name)}</b> — {_esc(humanize(cat.coverage.method))}",
                               styles["Body"]))
        if cat.coverage.checks_run:
            story.append(Paragraph(
                f"<b>Tested:</b> {_esc(', '.join(cat.coverage.checks_run))}", styles["Meta"]
            ))
        if cat.coverage.checks_not_covered:
            story.append(Paragraph(
                f"<b>Not tested:</b> {_esc(', '.join(cat.coverage.checks_not_covered))}",
                styles["Meta"],
            ))
        if cat.coverage.notes:
            story.append(Paragraph(_esc(cat.coverage.notes), styles["Meta"]))
        story.append(Spacer(1, 0.05 * inch))

    limitations = (ctx.scope_limitations if ctx and ctx.scope_limitations else [])
    if limitations:
        story.append(Paragraph("Scope limitations", styles["SectionH2"]))
        story.append(ListFlowable(
            [ListItem(Paragraph(_esc(item), styles["Body"])) for item in limitations],
            bulletType="bullet", leftIndent=12,
        ))
    return story


def _appendix(view: _ReportView, styles) -> list:
    """Raw selectors, rule identifiers, and every occurrence.

    These belong in the report — they're what makes a finding reproducible —
    but not in the body, where a string like
    `section > div > div:nth-of-type(2) > button:nth-of-type(1)` interrupts a
    reader who can't act on it.
    """
    recommendations = [r for r in view.all_recommendations() if r.selector or r.rule_id]
    if not recommendations:
        return []

    story = [
        PageBreak(),
        Paragraph("Appendix — technical detail", styles["SectionH1"]),
        Paragraph(
            "Machine-readable identifiers for every finding, for the team implementing the fixes. "
            "CSS selectors are computed from the page as rendered at audit time and may change "
            "when the markup changes; use the DOM excerpt to confirm the element.",
            styles["Body"],
        ),
    ]

    rows = [[
        Paragraph("Rule", styles["CellHead"]),
        Paragraph("Category", styles["CellHead"]),
        Paragraph("Element / selector", styles["CellHead"]),
        Paragraph("Region", styles["CellHead"]),
    ]]
    for rec in recommendations:
        locator = rec.selector or rec.context or "—"
        rows.append([
            Paragraph(_esc(rec.rule_id or "—"), styles["Mono"]),
            Paragraph(_esc(humanize(rec.category)), styles["Cell"]),
            Paragraph(_esc(str(locator)), styles["Mono"]),
            Paragraph(_esc(rec.section or "—"), styles["Cell"]),
        ])

    table = Table(rows, colWidths=[1.5 * inch, 0.9 * inch, 3.6 * inch, 1.0 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    return story


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_recommendations(
    recommendations: list[Recommendation], across_categories: bool = False
) -> list[_Group]:
    """Collapse repeats of the same finding into one entry with a count.

    Within a category this merges the same check firing on many elements. With
    `across_categories`, it also merges the same underlying problem reported by
    two agents — a missing <title> is one fix, whether Accessibility or SEO
    raised it — which is what stops the action plan from double-counting work.
    """
    groups: dict[tuple, _Group] = {}
    for rec in recommendations:
        key = (rec.title,) if across_categories else (rec.category, rec.title)
        group = groups.get(key)
        if group is None:
            groups[key] = _Group(title=rec.title, lead=rec, members=[rec])
            continue
        group.members.append(rec)
        # Keep the most severe instance as the one that speaks for the group.
        if _SEVERITY_RANK.get(rec.severity, 9) < _SEVERITY_RANK.get(group.lead.severity, 9):
            group.lead = rec
    return list(groups.values())


def _score_color(score: float | None) -> colors.Color:
    if score is None:
        return _MUTED
    if score >= 90:
        return colors.HexColor("#15803d")
    if score >= 50:
        return colors.HexColor("#a16207")
    return colors.HexColor("#b91c1c")


def _fmt_score(score: float | None) -> str:
    return "N/A" if score is None else f"{round_half_up(score)}/100"


def _esc(text: object) -> str:
    """Escape text for ReportLab's mini-markup parser.

    Findings quote real page markup ("Page is missing a <title> element"), and
    unescaped angle brackets are parsed as tags — silently swallowing the very
    evidence the sentence exists to show.
    """
    if text is None:
        return ""
    return escape(str(text))
