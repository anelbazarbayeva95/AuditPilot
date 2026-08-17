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


class ScoreStatus(str, Enum):
    """Why a category has (or doesn't have) a score.

    A score of `None` used to be ambiguous — it could mean the agent crashed,
    the tool was unavailable, or the evidence was too poor to judge. Reports
    have to be able to say which, because "insufficient evidence" is a
    legitimate audit outcome and "the agent failed" is not the same claim.
    """

    SCORED = "scored"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_RUN = "not_run"


class DetectionMethod(str, Enum):
    """How a finding was produced — automated fact vs. model judgment.

    Keeping these apart is the difference between "LCP measured 4820ms" and
    "the hero feels unbalanced": both belong in a report, but they can't be
    presented with the same authority.
    """

    AUTOMATED = "automated"
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"


class ImpactLevel(str, Enum):
    """User/business impact of a finding, independent of its severity."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EffortLevel(str, Enum):
    """Roughly how much work the fix is."""

    QUICK = "quick"
    MODERATE = "moderate"
    INVOLVED = "involved"


class TimingBand(str, Enum):
    """When the fix should be scheduled, derived from impact + effort + confidence."""

    IMMEDIATE = "immediate"
    NEXT_SPRINT = "next_sprint"
    BACKLOG = "backlog"


class CoverageMethod(str, Enum):
    """How a category was assessed."""

    AUTOMATED = "automated"
    AI_ASSISTED = "ai_assisted"
    NOT_RUN = "not_run"


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
    dom_excerpt: Optional[str] = Field(
        default=None,
        description="Truncated real outerHTML of this element — the short DOM excerpt a "
        "developer needs to recognize the element without trusting a fragile selector.",
    )
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
    accessible_name: Optional[str] = Field(
        default=None,
        description="Accessible name resolved in real precedence order (aria-labelledby > "
        "aria-label > text content > value > title). Empty string means the element genuinely "
        "has no accessible name; None means the scraper didn't compute one (older payloads).",
    )
    name_source: Optional[str] = Field(
        default=None,
        description="Which mechanism supplied `accessible_name` — 'aria-labelledby', "
        "'aria-label', 'content', 'value', 'title', or 'none'.",
    )
    dom_excerpt: Optional[str] = Field(
        default=None, description="Truncated real outerHTML of this element."
    )
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
    final_url: Optional[str] = Field(
        default=None, description="URL actually landed on after redirects, if known."
    )
    http_status: Optional[int] = Field(
        default=None, description="HTTP status of the main document response, if known."
    )
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
    wcag_criterion: Optional[str] = Field(
        default=None,
        description="The WCAG success criterion this check maps to, e.g. "
        "'WCAG 4.1.2 — Name, Role, Value'. Set from a fixed per-check map, never inferred.",
    )
    dom_excerpt: Optional[str] = Field(
        default=None, description="Truncated real outerHTML of the offending element, if element-level."
    )
    accessible_name_computation: Optional[str] = Field(
        default=None,
        description="Plain-language trace of how the accessible name resolved to nothing, e.g. "
        "'no aria-labelledby, no aria-label, no text content, no value, no title'. Only set for "
        "name-related checks, and derived entirely from attributes actually captured.",
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
    fcp_ms: Optional[float] = None
    tbt_ms: Optional[float] = None
    speed_index_ms: Optional[float] = None


class PerformanceRunConfig(BaseModel):
    """The conditions a performance score was measured under.

    A Lighthouse number is meaningless without this: the same page scores very
    differently on mobile-emulated 4G than on an unthrottled desktop run, so a
    report that prints the score without the conditions isn't reproducible.
    Every field is read back out of the Lighthouse report itself.
    """

    lighthouse_version: Optional[str] = None
    form_factor: Optional[str] = Field(default=None, description="'mobile' or 'desktop'")
    screen_emulation: Optional[str] = Field(default=None, description="e.g. '1350x940 @1x'")
    throttling: Optional[str] = Field(
        default=None, description="Human-readable throttling summary, e.g. 'simulated 10240kbps down, 4x CPU'"
    )
    runs: int = Field(default=1, description="How many Lighthouse runs the reported metrics come from.")
    fetch_time: Optional[str] = None
    final_url: Optional[str] = None
    user_agent: Optional[str] = None


class PerformanceOpportunity(BaseModel):
    """One Lighthouse opportunity/diagnostic, with the real resources behind it.

    This is what turns "audit render-blocking resources" into "defer
    main.css (48 KB, ~320 ms)" — every value comes from the Lighthouse audit's
    own `details.items`, never estimated here.
    """

    audit_id: str
    title: str
    savings_ms: Optional[float] = None
    savings_bytes: Optional[int] = None
    resources: list[str] = Field(
        default_factory=list, description="Real resource URLs named by the audit, largest first."
    )


class PerformanceFinding(BaseModel):
    check: PerformanceCheck
    severity: Severity
    message: str
    context: Optional[str] = None
    measured_value: Optional[str] = Field(default=None, description="e.g. '4820 ms'")
    threshold: Optional[str] = Field(default=None, description="e.g. 'good is <= 2500 ms'")


class PerformanceResult(BaseModel):
    """Output of the PerformanceAgent: {score, findings, metrics, run_config, opportunities}."""

    score: Optional[float] = Field(default=None, ge=0, le=100)
    findings: list[PerformanceFinding] = Field(default_factory=list)
    metrics: PerformanceMetrics
    run_config: Optional[PerformanceRunConfig] = None
    opportunities: list[PerformanceOpportunity] = Field(default_factory=list)


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


class ScreenshotQuality(BaseModel):
    """Whether a captured screenshot is actually usable as visual evidence.

    A headless capture can succeed at the protocol level and still be a mostly
    blank page — lazy-loaded hero media that never fired, fonts that never
    resolved, a consent overlay that swallowed the layout. Evaluating such a
    render as if it were the real page is how a report ends up describing a
    headline that isn't in its own screenshot, so the pipeline measures the
    render and refuses to judge it when it doesn't hold up.
    """

    status: str = Field(description="'ok', 'degraded', or 'unknown' (couldn't be measured).")
    dominant_color_pct: Optional[float] = Field(
        default=None, description="Share of pixels that are the single most common color, 0-100."
    )
    uniform_row_pct: Optional[float] = Field(
        default=None, description="Share of rows that are >99% a single color, 0-100."
    )
    content_top_pct: Optional[float] = Field(
        default=None,
        description="How far down the image the first content-bearing row appears, 0-100. A high "
        "value means the top of the page rendered empty.",
    )
    reason: Optional[str] = Field(
        default=None, description="Why the render was judged degraded, in plain language."
    )

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"


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

class CategoryCoverage(BaseModel):
    """What a category actually tested — and, just as importantly, what it didn't.

    A score is only interpretable next to its scope: "100/100" across six
    automated checks is a different claim from "100/100, SEO is fine". Every
    category publishes this so the report can state its own limits instead of
    implying completeness it never had.
    """

    checks_run: list[str] = Field(default_factory=list)
    checks_not_covered: list[str] = Field(default_factory=list)
    method: CoverageMethod = CoverageMethod.AUTOMATED
    notes: Optional[str] = None


class Evidence(BaseModel):
    """The raw observation behind a finding, so a reader can check the work."""

    dom_excerpt: Optional[str] = None
    accessible_name_computation: Optional[str] = None
    measured_value: Optional[str] = Field(default=None, description="e.g. '4820 ms', '0.31'")
    threshold: Optional[str] = Field(default=None, description="e.g. 'good is <= 2500 ms'")


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
    # -- provenance and planning fields -------------------------------------
    # All optional and None-by-default, like every other evidence field here:
    # absent means "not determined for this finding", never a plausible guess.
    wcag_criterion: Optional[str] = Field(
        default=None, description="WCAG success criterion, for accessibility findings."
    )
    rule_id: Optional[str] = Field(
        default=None, description="Stable identifier of the check that produced this finding."
    )
    detection: Optional[DetectionMethod] = Field(
        default=None, description="Automated measurement, model judgment, or manual observation."
    )
    confidence: Optional[ConfidenceLevel] = Field(
        default=None, description="How certain this finding is. Deterministic checks are 'high'."
    )
    impact: Optional[ImpactLevel] = None
    effort: Optional[EffortLevel] = None
    timing: Optional[TimingBand] = None
    occurrences: Optional[int] = Field(
        default=None, description="How many distinct elements this finding covers, once grouped."
    )
    validation: Optional[str] = Field(
        default=None, description="How to verify the fix actually landed."
    )
    owner: Optional[str] = Field(
        default=None,
        description="Team/person responsible. Only ever set from caller-supplied configuration — "
        "AuditPilot has no way to know who owns a component and will not guess one.",
    )
    evidence: Optional[Evidence] = None


class CategoryResult(BaseModel):
    """Result produced by a single agent for one audit category."""

    category: AuditCategory
    score: Optional[float] = Field(
        default=None, ge=0, le=100, description="0-100 score for this category"
    )
    score_status: ScoreStatus = Field(
        default=ScoreStatus.SCORED,
        description="Whether `score` is a real score, or absent because the evidence was "
        "insufficient / the category never ran.",
    )
    score_explanation: Optional[str] = Field(
        default=None,
        description="The arithmetic behind `score`, in one line — e.g. '100 - (7 x 10 for empty "
        "buttons, capped at 30) = 70'. Lets a reader reproduce the number instead of trusting it.",
    )
    coverage: Optional[CategoryCoverage] = None
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

class RunContext(BaseModel):
    """How this audit was produced — rendered as the report's Methodology section.

    Without this, a score is an assertion. With it, a reader can reproduce the
    run or explain the number away: a mobile-emulated, throttled Lighthouse
    score sitting next to a desktop screenshot is a very different result from
    what it looks like undisclosed.
    """

    started_at: datetime
    finished_at: Optional[datetime] = None
    requested_url: str
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    viewport: Optional[str] = Field(default=None, description="e.g. '1280x900'")
    user_agent: Optional[str] = None
    scraper_wait_until: Optional[str] = None
    wcag_target: str = "WCAG 2.2 AA"
    report_version: str = "1.0"
    performance_run: Optional[PerformanceRunConfig] = None
    scope_limitations: list[str] = Field(
        default_factory=list,
        description="Plain-language limits of this audit (single URL, single run, no "
        "authenticated states, automated checks only, ...).",
    )


class ReportSummary(BaseModel):
    """Top-level rollup: overall score, per-category scores, issue counts by severity."""

    overall_score: Optional[float] = Field(default=None, ge=0, le=100)
    category_scores: dict[str, Optional[float]] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(
        default_factory=dict, description="Recommendation count keyed by severity, e.g. {'high': 3}"
    )
    weights: dict[str, float] = Field(
        default_factory=dict,
        description="Weight each category contributed to `overall_score`, renormalized over the "
        "categories that actually produced one.",
    )
    excluded_categories: dict[str, str] = Field(
        default_factory=dict,
        description="Categories left out of `overall_score`, mapped to why — so an incomplete "
        "audit reads as incomplete instead of quietly averaging over a smaller set.",
    )
    score_explanation: Optional[str] = Field(
        default=None, description="How `overall_score` was computed, in one line."
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
    screenshot_quality: Optional[ScreenshotQuality] = Field(
        default=None,
        description="Measured usability of the captured render. A 'degraded' result is disclosed "
        "wherever the screenshot appears, and suppresses visual scoring rather than being "
        "evaluated as a successful render.",
    )
    run_context: Optional[RunContext] = Field(
        default=None, description="Methodology: how, when, and under what conditions this ran."
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
