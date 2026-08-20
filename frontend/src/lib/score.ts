import type { CategoryResult, DetectionMethod, Severity } from "@/types/audit"

export type ScoreBand = "excellent" | "good" | "needs-work" | "poor" | "unknown"

/**
 * Buckets a 0-100 score into a qualitative band.
 *
 * The thresholds are the same ones the PDF prints under the overall score
 * (`labels.SCORE_BANDS` in the backend). A number without a band is a number
 * the reader has to interpret unaided — "61/100" says nothing until the scale
 * says whether that's a crisis or a decent week — so the two must not drift.
 */
export function getScoreBand(score: number | null): ScoreBand {
  if (score === null) return "unknown"
  if (score >= 90) return "excellent"
  if (score >= 70) return "good"
  if (score >= 40) return "needs-work"
  return "poor"
}

export const scoreBandLabel: Record<ScoreBand, string> = {
  excellent: "Excellent",
  good: "Good",
  "needs-work": "Needs attention",
  poor: "Critical",
  unknown: "Unavailable",
}

/** The published scale, shown beside the score so the bands aren't a private convention. */
export const SCORE_SCALE = "0–39 Critical · 40–69 Needs attention · 70–89 Good · 90–100 Excellent"

/** Tailwind classes for the Progress indicator, keyed by band. */
export const scoreBandIndicatorClass: Record<ScoreBand, string> = {
  excellent: "bg-[var(--status-excellent-bar)]",
  good: "bg-[var(--status-good-bar)]",
  "needs-work": "bg-[var(--status-needs-work-bar)]",
  poor: "bg-[var(--status-poor-bar)]",
  unknown: "bg-muted-foreground/40",
}

/** Tailwind text-color classes for the qualitative status label, keyed by band. */
export const scoreBandTextClass: Record<ScoreBand, string> = {
  excellent: "text-[var(--status-excellent)]",
  good: "text-status-good",
  "needs-work": "text-status-needs-work",
  poor: "text-status-poor",
  unknown: "text-muted-foreground",
}

/** Same bands, brighter variants for legible score numbers on the dark ink sidebar/panels. */
export const scoreBandOnDarkTextClass: Record<ScoreBand, string> = {
  excellent: "text-[var(--status-excellent-on-dark)]",
  good: "text-[var(--status-good-on-dark)]",
  "needs-work": "text-[var(--status-needs-work-on-dark)]",
  poor: "text-[var(--status-poor-on-dark)]",
  unknown: "text-ink-muted",
}

// ---------------------------------------------------------------------------
// Provenance — measured fact vs model judgment vs withheld
//
// This is the distinction the product is actually built around, so it gets a
// visible, consistent treatment rather than being left to prose. It uses its
// own colour axis (teal / violet / slate); severity hues never appear here and
// these never appear as severity, so neither meaning gets diluted.
// ---------------------------------------------------------------------------

export type Provenance = "measured" | "judgment" | "withheld"

export function provenanceOf(detection: DetectionMethod | null | undefined): Provenance {
  if (detection === "ai_generated") return "judgment"
  if (detection === "automated" || detection === "manual") return "measured"
  return "measured"
}

export const provenanceLabel: Record<Provenance, string> = {
  measured: "Measured",
  judgment: "AI judgment",
  withheld: "Evidence withheld",
}

/** One-line explanation of what that label commits the report to. */
export const provenanceTooltip: Record<Provenance, string> = {
  measured: "Detected by a deterministic check against the rendered page.",
  judgment: "An AI-generated observation, not a measurement. Review before acting.",
  withheld: "The evidence did not meet the quality threshold, so no assessment was made.",
}

export const provenanceChipClass: Record<Provenance, string> = {
  measured: "bg-measured-bg text-measured",
  judgment: "bg-judgment-bg text-judgment",
  withheld: "bg-withheld-bg text-withheld",
}

/** How a category was assessed — drives the scorecard's Confidence column. */
export function categoryConfidence(category: CategoryResult): {
  label: string
  provenance: Provenance
} {
  if (category.score_status && category.score_status !== "scored") {
    return { label: "—", provenance: "withheld" }
  }
  if (category.coverage?.method === "ai_assisted") {
    return { label: "Medium — model judgment", provenance: "judgment" }
  }
  return { label: "High — automated checks", provenance: "measured" }
}

export const severityBadgeVariant: Record<
  Severity,
  "destructive" | "warning" | "secondary" | "outline"
> = {
  critical: "destructive",
  high: "destructive",
  medium: "warning",
  low: "secondary",
  info: "outline",
}

export function formatScore(score: number | null): string {
  return score === null ? "—" : Math.round(score).toString()
}

/** "high" -> "High Severity" — a full status label, never styled as a clickable action. */
export function severityLabel(severity: Severity): string {
  return `${severity.charAt(0).toUpperCase()}${severity.slice(1)} Severity`
}

/**
 * Left-edge accent stripe color per severity, for use on light (card-on-page)
 * backgrounds. A badge alone is easy to skim past; a stripe reads in
 * peripheral vision, so critical/high findings visually stand out from
 * medium/low ones without any new data — same severity the backend already
 * computed, just more visually weighted.
 */
export const severityStripeClass: Record<Severity, string> = {
  critical: "bg-severity-critical",
  high: "bg-severity-high",
  medium: "bg-severity-medium",
  low: "bg-severity-low/30",
  info: "bg-severity-low/25",
}

/** Text colour per severity, for the compact label beside a finding title. */
export const severityTextClass: Record<Severity, string> = {
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
  info: "text-severity-low",
}

/** Tinted chip background per severity — paired with the text colour above. */
export const severityChipClass: Record<Severity, string> = {
  critical: "bg-severity-critical-bg text-severity-critical",
  high: "bg-severity-high-bg text-severity-high",
  medium: "bg-severity-medium-bg text-severity-medium",
  low: "bg-severity-low-bg text-severity-low",
  info: "bg-severity-low-bg text-severity-low",
}

/** Only critical/high findings get "raised" (tinted background, accent
 *  stripe) — medium/low stay at neutral card weight so the hierarchy reads
 *  as "these need attention first," not just decoration on every card. */
export function isElevatedSeverity(severity: Severity): boolean {
  return severity === "critical" || severity === "high"
}
