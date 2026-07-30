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

/** Gemini's self-reported certainty in one Copy/Visual insight. Never shown for
 * rule-based Accessibility/SEO/Performance findings — those are deterministic. */
export type ConfidenceLevel = "high" | "medium" | "low"

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
  summary: string | null
  recommendations: Recommendation[]
  raw_data: RuleRawData | CopyRawData | VisualRawData | Record<string, unknown> | null
}

/** `summary` block of StructuredAuditReport (POST /report). */
export interface ReportSummary {
  overall_score: number | null
  category_scores: Record<string, number | null>
  issue_counts: Record<string, number>
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
  screenshot_full_page_base64: string | null
  screenshot_viewport_base64: string | null
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
}
