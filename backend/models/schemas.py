"""
Pydantic models for AuditPilot.

Defines the request/response contracts shared between the FastAPI layer,
the orchestrator, and the individual agents. No business logic here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class AuditCategory(str, Enum):
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    SEO = "seo"
    COPY = "copy"
    VISUAL = "visual"


class AuditStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    """Incoming request to audit a single URL."""

    url: HttpUrl
    categories: list[AuditCategory] = Field(
        default_factory=lambda: list(AuditCategory),
        description="Which audit categories to run. Defaults to all.",
    )


class ScrapeRequest(BaseModel):
    """Incoming request to scrape a single URL (POST /audit, Milestone 1)."""

    url: HttpUrl


# ---------------------------------------------------------------------------
# Scraped page data (Milestone 1: Playwright scraping)
# ---------------------------------------------------------------------------

class ImageData(BaseModel):
    """A single <img> element found on the page."""

    src: str
    alt: Optional[str] = None
    # Real, captured-off-the-live-DOM evidence (all optional, never fabricated
    # — None simply means the scraper couldn't determine it, e.g. the image
    # hadn't finished loading so naturalWidth/naturalHeight were 0).
    width: Optional[int] = None
    height: Optional[int] = None
    selector: Optional[str] = Field(
        default=None,
        description="CSS selector computed from real DOM structure (id if present, else a "
        "positional nth-of-type path) — lets a finding point at exactly this element.",
    )
    section: Optional[str] = Field(
        default=None,
        description="Nearest real landmark ancestor (Header/Navigation/Footer/Main content), "
        "or None if the element isn't inside one.",
    )


class ButtonData(BaseModel):
    """A single clickable button-like element found on the page."""

    text: str
    # Real DOM attributes captured alongside `text` (all optional — plenty of
    # buttons have none of these) so a button with no accessible name can
    # still be pointed to by something concrete instead of just its position
    # in the list. Never fabricated: each is either the attribute's literal
    # value or None if the element didn't have it.
    id: Optional[str] = None
    class_name: Optional[str] = None
    button_type: Optional[str] = None
    selector: Optional[str] = Field(
        default=None,
        description="CSS selector computed from real DOM structure (id if present, else a "
        "positional nth-of-type path) — lets a finding point at exactly this element.",
    )
    section: Optional[str] = Field(
        default=None,
        description="Nearest real landmark ancestor (Header/Navigation/Footer/Main content), "
        "or None if the element isn't inside one.",
    )


class LinkData(BaseModel):
    """A single <a href> element found on the page."""

    text: Optional[str] = None
    href: str


class InputData(BaseModel):
    """A single form field (input/textarea/select) found on the page."""

    type: str
    id: Optional[str] = None
    name: Optional[str] = None
    has_label: bool = Field(
        description="Whether the field has an associated accessible name "
        "(label[for], wrapping <label>, aria-label, or aria-labelledby)."
    )


class ScrapedPageData(BaseModel):
    """Structured content extracted from a single rendered page."""

    url: str
    title: Optional[str] = None
    meta_description: Optional[str] = None
    h1_tags: list[str] = Field(default_factory=list)
    h2_tags: list[str] = Field(default_factory=list)
    images: list[ImageData] = Field(default_factory=list)
    buttons: list[ButtonData] = Field(default_factory=list)
    links: list[LinkData] = Field(default_factory=list)
    inputs: list[InputData] = Field(default_factory=list)
    open_graph: dict[str, str] = Field(
        default_factory=dict,
        description="Open Graph meta tags keyed by lowercase property, e.g. 'og:title' -> content",
    )


# ---------------------------------------------------------------------------
# Accessibility agent (Milestone 2)
# ---------------------------------------------------------------------------

class AccessibilityCheck(str, Enum):
    """Identifiers for each rule the AccessibilityAgent evaluates."""

    MISSING_ALT_TEXT = "missing_alt_text"
    MULTIPLE_H1 = "multiple_h1"
    EMPTY_BUTTON = "empty_button"
    MISSING_LABEL = "missing_label"
    MISSING_PAGE_TITLE = "missing_page_title"


class AccessibilityFinding(BaseModel):
    """A single accessibility issue detected on the page."""

    check: AccessibilityCheck
    severity: Severity
    message: str
    context: Optional[str] = Field(
        default=None, description="Offending element/value, e.g. an image src or field name"
    )
    selector: Optional[str] = Field(
        default=None, description="Real CSS selector for the offending element, if this check is element-level."
    )
    section: Optional[str] = Field(
        default=None, description="Nearest real landmark (Header/Navigation/Footer/Main content), if known."
    )
    ai_suggestion: Optional[str] = Field(
        default=None,
        description="Gemini-generated suggested replacement (e.g. a suggested <title> or alt "
        "text), filled in by a best-effort enrichment pass — always a suggestion, never "
        "asserted as a detected fact. None if generation wasn't attempted or failed.",
    )


class AccessibilityResult(BaseModel):
    """Output of the AccessibilityAgent: {score, findings}."""

    score: float = Field(ge=0, le=100)
    findings: list[AccessibilityFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SEO agent (Milestone 3)
# ---------------------------------------------------------------------------

class SEOCheck(str, Enum):
    """Identifiers for each rule the SEOAgent evaluates."""

    MISSING_TITLE = "missing_title"
    MISSING_META_DESCRIPTION = "missing_meta_description"
    MISSING_H1 = "missing_h1"
    MULTIPLE_H1 = "multiple_h1"
    MISSING_OPEN_GRAPH_TAGS = "missing_open_graph_tags"
    MISSING_IMAGE_ALT_TEXT = "missing_image_alt_text"


class SEOFinding(BaseModel):
    """A single SEO issue detected on the page."""

    check: SEOCheck
    severity: Severity
    message: str
    context: Optional[str] = Field(
        default=None, description="Offending element/value, e.g. an og: tag name or image src"
    )
    selector: Optional[str] = Field(
        default=None, description="Real CSS selector for the offending element, if this check is element-level."
    )
    section: Optional[str] = Field(
        default=None, description="Nearest real landmark (Header/Navigation/Footer/Main content), if known."
    )
    ai_suggestion: Optional[str] = Field(
        default=None,
        description="Gemini-generated suggested replacement (e.g. a suggested <title>), filled "
        "in by a best-effort enrichment pass — always a suggestion, never asserted as a "
        "detected fact. None if generation wasn't attempted or failed.",
    )


class SEOResult(BaseModel):
    """Output of the SEOAgent: {score, findings}."""

    score: float = Field(ge=0, le=100)
    findings: list[SEOFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Copy agent (Milestone 4 — Gemini-powered)
# ---------------------------------------------------------------------------

class CopyDimension(str, Enum):
    """The five dimensions the CopyAgent asks Gemini to evaluate."""

    VALUE_PROPOSITION_CLARITY = "value_proposition_clarity"
    READABILITY = "readability"
    CTA_QUALITY = "cta_quality"
    JARGON = "jargon"
    TRUST_SIGNALS = "trust_signals"


class ConfidenceLevel(str, Enum):
    """How certain Gemini is in a single subjective insight (Copy/Visual only).

    Rule-based agents (Accessibility/SEO/Performance) don't get a confidence
    field — their findings are deterministic checks against fixed thresholds,
    not judgment calls, so a confidence score would be meaningless there.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CopyInsight(BaseModel):
    """A single strength/weakness/recommendation tied to one copy dimension."""

    dimension: CopyDimension
    point: str
    confidence: Optional[ConfidenceLevel] = Field(
        default=None,
        description="Gemini's self-reported certainty in this specific observation, if provided.",
    )


class CopyResult(BaseModel):
    """Output of the CopyAgent: strengths, weaknesses, recommendations."""

    strengths: list[CopyInsight] = Field(default_factory=list)
    weaknesses: list[CopyInsight] = Field(default_factory=list)
    recommendations: list[CopyInsight] = Field(default_factory=list)
    score: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="Gemini's holistic 0-100 copy quality score, if provided.",
    )


# ---------------------------------------------------------------------------
# Performance agent (Milestone 7 — Lighthouse)
# ---------------------------------------------------------------------------

class PerformanceCheck(str, Enum):
    LOW_PERFORMANCE_SCORE = "low_performance_score"
    SLOW_LCP = "slow_lcp"
    HIGH_CLS = "high_cls"
    SLOW_INP = "slow_inp"


class PerformanceMetrics(BaseModel):
    """Raw Core Web Vitals extracted from a Lighthouse report."""

    performance_score: Optional[float] = Field(default=None, ge=0, le=100)
    lcp_ms: Optional[float] = None
    cls: Optional[float] = None
    inp_ms: Optional[float] = None


class PerformanceFinding(BaseModel):
    check: PerformanceCheck
    severity: Severity
    message: str
    context: Optional[str] = None


class PerformanceResult(BaseModel):
    """Output of the PerformanceAgent: {score, findings, metrics}."""

    score: Optional[float] = Field(default=None, ge=0, le=100)
    findings: list[PerformanceFinding] = Field(default_factory=list)
    metrics: PerformanceMetrics


# ---------------------------------------------------------------------------
# Visual agent (Milestone 11 — Gemini vision analysis of screenshots)
# ---------------------------------------------------------------------------

class VisualDimension(str, Enum):
    """The four dimensions the VisualAgent asks Gemini to evaluate from screenshots."""

    VISUAL_HIERARCHY = "visual_hierarchy"
    CTA_VISIBILITY = "cta_visibility"
    LAYOUT_ISSUES = "layout_issues"
    CONTRAST_PROBLEMS = "contrast_problems"


class VisualInsight(BaseModel):
    """A single strength/weakness/recommendation tied to one visual dimension."""

    dimension: VisualDimension
    point: str
    confidence: Optional[ConfidenceLevel] = Field(
        default=None,
        description="Gemini's self-reported certainty in this specific observation, if provided.",
    )


class VisualResult(BaseModel):
    """Output of the VisualAgent: strengths, weaknesses, recommendations from the screenshots."""

    strengths: list[VisualInsight] = Field(default_factory=list)
    weaknesses: list[VisualInsight] = Field(default_factory=list)
    recommendations: list[VisualInsight] = Field(default_factory=list)
    score: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="Gemini's holistic 0-100 visual design quality score, if provided.",
    )


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class Recommendation(BaseModel):
    """A single actionable recommendation produced by an agent."""

    title: str
    description: str
    severity: Severity
    category: AuditCategory
    context: Optional[str] = Field(
        default=None,
        description="Distinguishing evidence for this specific occurrence (e.g. an element "
        "selector, image src, or form field name) — lets the frontend tell apart multiple "
        "findings that share the same title/description, e.g. several empty buttons.",
    )
    selector: Optional[str] = Field(
        default=None, description="Real CSS selector for the offending element, if this check is element-level."
    )
    section: Optional[str] = Field(
        default=None, description="Nearest real landmark (Header/Navigation/Footer/Main content), if known."
    )
    ai_suggestion: Optional[str] = Field(
        default=None,
        description="Gemini-generated suggested replacement (e.g. a suggested <title> or alt "
        "text) — always a suggestion, never asserted as a detected fact. None if generation "
        "wasn't attempted or failed.",
    )


class CategoryResult(BaseModel):
    """Result produced by a single agent for one audit category."""

    category: AuditCategory
    score: Optional[float] = Field(
        default=None, ge=0, le=100, description="0-100 score for this category"
    )
    summary: Optional[str] = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    raw_data: Optional[dict] = Field(
        default=None, description="Unprocessed data from the underlying tool (e.g. Lighthouse JSON)"
    )


# ---------------------------------------------------------------------------
# Orchestrator (Milestone 5)
# ---------------------------------------------------------------------------

class AuditResult(BaseModel):
    """Aggregated output of AuditOrchestrator.run(): one result per agent, plus an overall score.

    Note: the `copy` field name intentionally matches the spec's output shape
    ({overall_score, accessibility, seo, copy}). It shadows BaseModel's
    deprecated `.copy()` (Pydantic v1-era; superseded by `.model_copy()` in
    v2), which Pydantic flags with a harmless UserWarning at class-definition
    time. Field access always resolves to this field's value, not the
    deprecated method, so `result.copy.score` etc. behaves as expected.
    """

    overall_score: Optional[float] = Field(
        default=None, ge=0, le=100, description="Mean of the available per-category scores."
    )
    accessibility: CategoryResult
    seo: CategoryResult
    copy: CategoryResult


class PdfReportRequest(BaseModel):
    """Request body for POST /report/pdf (Milestone 8).

    Accepts an already-computed AuditResult (e.g. from POST /audit/full) so
    the PDF is built from real data without re-running the audit. Performance
    is passed separately since PerformanceAgent isn't wired into
    AuditOrchestrator/AuditResult yet.

    Superseded by StructuredPdfReportRequest (POST /report/pdf/full) for the
    current job-based flow, where the frontend already has one combined
    StructuredAuditReport instead of a bare AuditResult + separate
    performance/visual results. Kept as-is so its existing callers/tests
    keep working.
    """

    url: HttpUrl
    result: AuditResult
    performance: Optional[CategoryResult] = None
    visual: Optional[CategoryResult] = None
    screenshot_viewport_base64: Optional[str] = Field(
        default=None, description="Above-the-fold screenshot PNG, base64-encoded, embedded in the Visual section."
    )


# ---------------------------------------------------------------------------
# Structured report (Milestone 9 — combines all four agents)
# ---------------------------------------------------------------------------

class ReportSummary(BaseModel):
    """Top-level rollup: overall score, per-category scores, issue counts by severity."""

    overall_score: Optional[float] = Field(default=None, ge=0, le=100)
    category_scores: dict[str, Optional[float]] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(
        default_factory=dict, description="Recommendation count keyed by severity, e.g. {'high': 3}"
    )


class StructuredAuditReport(BaseModel):
    """Final combined report from all five agents: {summary, accessibility, seo, performance, copy, visual, recommendations}.

    `recommendations` is every agent's Recommendation list merged and sorted
    by severity (critical/high first) — this single list serves as both the
    prioritized issue list and the action-item list, since each entry already
    names the problem (title/description) and its fix.

    `screenshot_*_base64` (Milestone 11) are the raw PNGs VisualAgent analyzed,
    base64-encoded so the frontend can render them directly without a
    separate file-serving endpoint. Both are None if screenshot capture
    failed (VisualAgent's failure is isolated like every other agent's).
    """

    summary: ReportSummary
    accessibility: CategoryResult
    seo: CategoryResult
    performance: CategoryResult
    copy: CategoryResult
    visual: CategoryResult
    recommendations: list[Recommendation] = Field(default_factory=list)
    screenshot_full_page_base64: Optional[str] = Field(
        default=None, description="Full-page screenshot PNG, base64-encoded."
    )
    screenshot_viewport_base64: Optional[str] = Field(
        default=None, description="Above-the-fold viewport screenshot PNG, base64-encoded."
    )


class StructuredPdfReportRequest(BaseModel):
    """Request body for POST /report/pdf/full — the current export path.

    Unlike PdfReportRequest (legacy, pre-job-based-flow), the frontend already
    holds one complete StructuredAuditReport for a finished job (all five
    agents + screenshots combined), so this just wraps that plus the audited
    URL — no separate performance/visual params needed.
    """

    url: HttpUrl
    report: StructuredAuditReport


# ---------------------------------------------------------------------------
# Background report jobs (Milestone 10 — real polling-based progress)
# ---------------------------------------------------------------------------

class ReportJob(BaseModel):
    """State of one background /report/jobs run, polled by the frontend's Audit Progress page.

    `progress` keys are step names ("scrape", "accessibility", "seo", "copy",
    "performance"), each one of "pending" | "running" | "completed" | "failed".
    """

    id: str
    url: str
    status: AuditStatus
    progress: dict[str, str] = Field(default_factory=dict)
    result: Optional[StructuredAuditReport] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class AuditReport(BaseModel):
    """Full audit report for a URL, aggregating all category results."""

    id: str
    url: HttpUrl
    status: AuditStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    overall_score: Optional[float] = Field(default=None, ge=0, le=100)
    results: list[CategoryResult] = Field(default_factory=list)
    error: Optional[str] = None


class AuditJobResponse(BaseModel):
    """Response returned immediately after submitting an audit request."""

    id: str
    status: AuditStatus
    url: HttpUrl


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "auditpilot-backend"
    version: str = "0.1.0"
