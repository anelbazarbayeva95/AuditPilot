import type { Severity } from "@/types/audit"

export type ScoreBand = "good" | "needs-work" | "poor" | "unknown"

/** Buckets a 0-100 score into a qualitative band for color-coding. */
export function getScoreBand(score: number | null): ScoreBand {
  if (score === null) return "unknown"
  if (score >= 90) return "good"
  if (score >= 50) return "needs-work"
  return "poor"
}

export const scoreBandLabel: Record<ScoreBand, string> = {
  good: "Good",
  "needs-work": "Needs work",
  poor: "Poor",
  unknown: "Unavailable",
}

/** Tailwind classes for the Progress indicator, keyed by band. */
export const scoreBandIndicatorClass: Record<ScoreBand, string> = {
  good: "bg-[var(--status-good-bar)]",
  "needs-work": "bg-[var(--status-needs-work-bar)]",
  poor: "bg-[var(--status-poor-bar)]",
  unknown: "bg-muted-foreground/40",
}

/** Tailwind text-color classes for the qualitative status label, keyed by band. */
export const scoreBandTextClass: Record<ScoreBand, string> = {
  good: "text-status-good",
  "needs-work": "text-status-needs-work",
  poor: "text-status-poor",
  unknown: "text-muted-foreground",
}

/** Same bands, brighter variants for legible score numbers on the dark ink sidebar/panels. */
export const scoreBandOnDarkTextClass: Record<ScoreBand, string> = {
  good: "text-[var(--status-good-on-dark)]",
  "needs-work": "text-[var(--status-needs-work-on-dark)]",
  poor: "text-[var(--status-poor-on-dark)]",
  unknown: "text-ink-muted",
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
  critical: "bg-[oklch(38%_0.16_22)]",
  high: "bg-destructive",
  medium: "bg-warning",
  low: "bg-muted-foreground/25",
  info: "bg-muted-foreground/25",
}

/** Only critical/high findings get "raised" (tinted background, accent
 *  stripe) — medium/low stay at neutral card weight so the hierarchy reads
 *  as "these need attention first," not just decoration on every card. */
export function isElevatedSeverity(severity: Severity): boolean {
  return severity === "critical" || severity === "high"
}
