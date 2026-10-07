/**
 * TypeScript mirrors of the backend Pydantic models
 * (backend/models/schemas.py) returned by POST /audit/full.
 *
 * Keep in sync with the backend — these are hand-written, not generated.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info"

export type AuditCategory = "accessibility" | "performance" | "seo" | "copy" | "visual"

export type CopyDimension =
  | "value_proposition_clarity"
  | "readability"
  | "cta_quality"
  | "jargon"
  | "trust_signals"

export type VisualDimension =
  | "visual_hierarchy"
  | "cta_visibility"
  | "layout_issues"
  | "contrast_problems"

/** Gemini's self-reported certainty in one Copy/Visual insight. Rule-based
 * Accessibility/SEO/Performance findings report "high" — they're deterministic. */
export type ConfidenceLevel = "high" | "medium" | "low"

/** Why a category has (or doesn't have) a score. "insufficient_evidence" means
 * the audit declined to judge — e.g. the page render was incomplete — which is
 * a different claim from the agent having failed. */
export type ScoreStatus = "scored" | "insufficient_evidence" | "not_run"

/** Whether a finding is a measurement or a model judgment. */
export type DetectionMethod = "automated" | "ai_generated" | "manual"

export type ImpactLevel = "high" | "medium" | "low"
export type EffortLevel = "quick" | "moderate" | "involved"
export type TimingBand = "immediate" | "next_sprint" | "backlog"
export type CoverageMethod = "automated" | "ai_assisted" | "not_run"

/** What a category tested, and what it explicitly did not. */
export interface CategoryCoverage {
  checks_run: string[]
  checks_not_covered: string[]
  method: CoverageMethod
  notes?: string | null
}

/** The raw observation behind a finding. */
export interface Evidence {
  dom_excerpt?: string | null
  accessible_name_computation?: string | null
  measured_value?: string | null
  threshold?: string | null
}

export interface Recommendation {
  title: string
  description: string
  severity: Severity
  category: AuditCategory
  /** Distinguishing evidence for this specific occurrence (element selector-ish
   * label, image src, form field name, etc) — lets the UI tell apart multiple
   * findings that share the same title, e.g. several empty buttons. */
  context?: string | null
  /** Real CSS selector computed from actual DOM structure, when this finding
   * is element-level (an image or button) rather than page-level. */
  selector?: string | null
  /** Nearest real landmark ancestor — "Header", "Navigation", "Footer", "Main
   * content" — or null if the element isn't inside one, or the finding is
   * page-level (e.g. a missing page title). */
  section?: string | null
  /** Gemini-generated suggested replacement (a suggested <title> or alt
   * text), filled in by a best-effort backend enrichment pass. Always a
   * suggestion to review, never asserted as a detected fact — null if
   * generation wasn't attempted or failed for this finding. */
  ai_suggestion?: string | null
  /** WCAG success criterion, for accessibility findings — e.g.
   * "WCAG 4.1.2 — Name, Role, Value (Level A)". */
  wcag_criterion?: string | null
  /** Stable identifier of the check behind this finding (`empty_button`,
   * `slow_lcp`). Prefer this over `title` when keying lookups — titles are
   * editorial and can be reworded. */
  rule_id?: string | null
  detection?: DetectionMethod | null
  confidence?: ConfidenceLevel | null
  impact?: ImpactLevel | null
  effort?: EffortLevel | null
  timing?: TimingBand | null
  /** How many distinct elements this finding covers, once grouped. */
  occurrences?: number | null
  /** How to verify the fix landed. */
  validation?: string | null
  /** Only ever set from caller-supplied configuration — never inferred. */
  owner?: string | null
  evidence?: Evidence | null
}

/** A single strength/weakness/recommendation from CopyAgent, tied to one dimension. */
export interface CopyInsight {
  dimension: CopyDimension
  point: string
  confidence?: ConfidenceLevel | null
}

/** Shape of CopyResult, as it appears inside CategoryResult.raw_data for the copy category. */
export interface CopyRawData {
  strengths: CopyInsight[]
  weaknesses: CopyInsight[]
  recommendations: CopyInsight[]
  score: number | null
}

/** A single strength/weakness/recommendation from VisualAgent, tied to one dimension. */
export interface VisualInsight {
  dimension: VisualDimension
  point: string
  confidence?: ConfidenceLevel | null
}

/** Shape of VisualResult, as it appears inside CategoryResult.raw_data for the visual category. */
export interface VisualRawData {
  strengths: VisualInsight[]
  weaknesses: VisualInsight[]
  recommendations: VisualInsight[]
  score: number | null
}

/** A single accessibility/SEO finding, as it appears inside CategoryResult.raw_data. */
export interface RuleFinding {
  check: string
  severity: Severity
  message: string
  context?: string | null
}

export interface RuleRawData {
  score: number
  findings: RuleFinding[]
}

export interface CategoryResult {
  category: AuditCategory
  score: number | null
  /** Defaults to "scored" on older payloads. */
  score_status?: ScoreStatus
  /** The arithmetic behind `score`, in one line. */
  score_explanation?: string | null
  coverage?: CategoryCoverage | null
  summary: string | null
  recommendations: Recommendation[]
  raw_data: RuleRawData | CopyRawData | VisualRawData | Record<string, unknown> | null
}

/** `summary` block of StructuredAuditReport (POST /report). */
export interface ReportSummary {
  overall_score: number | null
  category_scores: Record<string, number | null>
  issue_counts: Record<string, number>
  /** Weight each category contributed, renormalized over those that scored. */
  weights?: Record<string, number>
  /** Categories left out of `overall_score`, mapped to why. */
  excluded_categories?: Record<string, string>
  score_explanation?: string | null
}

/** Measured usability of the captured render. A "degraded" status means the
 * screenshot documents a failed capture, not the page — the backend skips
 * visual scoring in that case, and the UI must not present it as the design. */
export interface ScreenshotQuality {
  status: "ok" | "degraded" | "unknown"
  dominant_color_pct?: number | null
  uniform_row_pct?: number | null
  content_top_pct?: number | null
  reason?: string | null
}

/** One Lighthouse opportunity, with the real resources and measured savings. */
export interface PerformanceOpportunity {
  audit_id: string
  title: string
  savings_ms?: number | null
  savings_bytes?: number | null
  resources: string[]
}

/**
 * One unit of work in the priority plan.
 *
 * Distinct from `Recommendation`: a recommendation is a finding, an action is
 * a fix. Several findings across several categories can share one action, so
 * this carries `categories` and `findings_resolved` rather than one category.
 */
export interface ActionItem {
  key: string
  title: string
  description: string
  categories: string[]
  rule_ids: string[]
  findings_resolved: number
  severity: Severity
  impact?: ImpactLevel | null
  effort?: EffortLevel | null
  timing?: TimingBand | null
  confidence?: ConfidenceLevel | null
  detection?: DetectionMethod | null
  primary_standard?: string | null
  estimated_saving?: string | null
  validation?: string | null
  owner?: string | null
}

/** How the audit was produced — the report's methodology. */
export interface PerformanceRunConfig {
  lighthouse_version?: string | null
  form_factor?: string | null
  screen_emulation?: string | null
  throttling?: string | null
  runs: number
  fetch_time?: string | null
  final_url?: string | null
  user_agent?: string | null
}

export interface RunContext {
  started_at: string
  finished_at?: string | null
  requested_url: string
  final_url?: string | null
  http_status?: number | null
  viewport?: string | null
  user_agent?: string | null
  scraper_wait_until?: string | null
  wcag_target: string
  report_version: string
  performance_run?: PerformanceRunConfig | null
  scope_limitations: string[]
}

/**
 * Combined report from all five agents (POST /report, and the `result` field
 * of a completed ReportJob). This is what the Results Dashboard renders.
 *
 * `screenshot_*_base64` (Milestone 11) are the PNGs VisualAgent analyzed,
 * base64-encoded — render as `data:image/png;base64,${...}`. Both are null
 * if screenshot capture failed (isolated like any other agent failure).
 */
export interface StructuredAuditReport {
  summary: ReportSummary
  accessibility: CategoryResult
  seo: CategoryResult
  performance: CategoryResult
  copy: CategoryResult
  visual: CategoryResult
  recommendations: Recommendation[]
  /** Findings consolidated into units of work — one entry per fix, not per finding. */
  action_plan?: ActionItem[]
  /** Outcome metrics deliberately kept out of the plan (e.g. the Lighthouse score). */
  kpi_notes?: string[]
  screenshot_full_page_base64: string | null
  screenshot_viewport_base64: string | null
  screenshot_quality?: ScreenshotQuality | null
  run_context?: RunContext | null
}

export type JobStatus = "pending" | "running" | "completed" | "failed"

export type ReportJobStep = "scrape" | "accessibility" | "seo" | "copy" | "performance" | "visual"

export type StepState = "pending" | "running" | "completed" | "failed"

/** GET /report/jobs/{id} response — polled by the Audit Progress page. */
export interface ReportJob {
  id: string
  url: string
  status: JobStatus
  progress: Record<ReportJobStep, StepState>
  result: StructuredAuditReport | null
  error: string | null
  /** 1-based place in line while waiting for a free audit slot; null otherwise. */
  queue_position?: number | null
}
