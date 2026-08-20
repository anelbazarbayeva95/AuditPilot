/**
 * Turns a finished report into the few things a decision-maker needs first.
 *
 * The report already answers "what did the scanner find". The summary has to
 * answer a different question — "what do I now know, and what should I do" —
 * so these helpers derive the primary risk, the largest *measured* opportunity,
 * and how much of the audit can actually be relied on.
 *
 * Two rules hold throughout, both inherited from the backend's contract:
 * nothing is claimed that wasn't measured (an opportunity with no quantified
 * saving is omitted, not estimated), and a category the audit declined to score
 * is reported as withheld rather than quietly dropped from the denominator.
 */

import type {
  ActionItem,
  CategoryResult,
  PerformanceOpportunity,
  StructuredAuditReport,
} from "@/types/audit"

import { dedupeRecommendations, effortFor } from "./issueText"

const CATEGORY_LABEL: Record<string, string> = {
  accessibility: "Accessibility",
  seo: "SEO",
  performance: "Performance",
  copy: "Copy",
  visual: "Visual",
}

export function categoryLabel(key: string): string {
  return CATEGORY_LABEL[key] ?? key
}

/**
 * The consolidated action plan.
 *
 * Prefers the backend's plan, which merges findings that share one fix —
 * adding an alt attribute closes an Accessibility finding and an SEO finding
 * with one edit, and showing that as two tickets misrepresents the work. Falls
 * back to local de-duplication only for reports produced before the backend
 * carried a plan.
 */
export function actionsOf(report: StructuredAuditReport): ActionItem[] {
  if (report.action_plan && report.action_plan.length > 0) return report.action_plan

  return dedupeRecommendations(report.recommendations).map((issue) => ({
    key: issue.title,
    title: issue.title,
    description: issue.description,
    categories: issue.categories.map((c) => c.toLowerCase()),
    rule_ids: [],
    findings_resolved: 1,
    severity: issue.severity,
    effort: effortFor(issue.title) === "quick" ? "quick" : "moderate",
  }))
}

export interface EvidenceStatus {
  assessed: number
  total: number
  withheld: Array<{ label: string; reason: string }>
}

/** How much of this audit produced usable evidence — and what didn't. */
export function evidenceStatus(report: StructuredAuditReport): EvidenceStatus {
  const categories: Array<[string, CategoryResult]> = [
    ["accessibility", report.accessibility],
    ["seo", report.seo],
    ["performance", report.performance],
    ["copy", report.copy],
    ["visual", report.visual],
  ]

  const withheld = categories
    .filter(([, cat]) => (cat.score_status ?? "scored") !== "scored" || cat.score === null)
    .map(([key, cat]) => ({
      label: categoryLabel(key),
      reason:
        cat.score_status === "insufficient_evidence"
          ? "insufficient evidence"
          : cat.score_status === "not_run"
            ? "did not run"
            : "no score produced",
    }))

  return {
    assessed: categories.length - withheld.length,
    total: categories.length,
    withheld,
  }
}

function opportunitiesOf(performance: CategoryResult): PerformanceOpportunity[] {
  const raw = performance.raw_data as { opportunities?: PerformanceOpportunity[] } | null
  return Array.isArray(raw?.opportunities) ? raw.opportunities : []
}

/**
 * Total measured load-time saving, or null when nothing was quantified.
 *
 * Returning null rather than a vague "significant opportunity" is deliberate:
 * an unquantified claim is exactly what makes an audit disbelieved.
 */
export function measuredSavings(
  report: StructuredAuditReport
): { seconds: number; leaders: string[] } | null {
  const opportunities = opportunitiesOf(report.performance)
  const totalMs = opportunities.reduce((sum, o) => sum + (o.savings_ms ?? 0), 0)
  if (totalMs <= 0) return null

  return {
    seconds: totalMs / 1000,
    leaders: opportunities
      .filter((o) => (o.savings_ms ?? 0) > 0)
      .slice(0, 2)
      .map((o) => o.title),
  }
}

export interface KeyMessage {
  label: string
  body: string
  tone: "risk" | "opportunity" | "confidence"
}

/** The three sentences the summary should lead with. */
export function keyMessages(report: StructuredAuditReport): KeyMessage[] {
  const messages: KeyMessage[] = []
  const actions = actionsOf(report)
  const top = actions[0]

  if (top) {
    const detail =
      top.findings_resolved > 1
        ? `${top.findings_resolved} findings ${
            top.categories.length > 1 ? "across" : "in"
          } ${top.categories.map(categoryLabel).join(" and ")} resolve with this one fix.`
        : top.description
    messages.push({ label: "Primary risk", body: `${top.title}. ${detail}`, tone: "risk" })
  }

  const savings = measuredSavings(report)
  if (savings) {
    messages.push({
      label: "Largest measured opportunity",
      body:
        `About ${savings.seconds.toFixed(1)}s of load time identified as recoverable` +
        (savings.leaders.length > 0 ? `, led by: ${savings.leaders.join("; ")}.` : "."),
      tone: "opportunity",
    })
  }

  const evidence = evidenceStatus(report)
  const withheldText =
    evidence.withheld.length > 0
      ? ` ${evidence.withheld.map((w) => `${w.label} was withheld (${w.reason})`).join("; ")}.`
      : ""
  messages.push({
    label: "Audit confidence",
    body: `${evidence.assessed} of ${evidence.total} categories produced reliable evidence.${withheldText}`,
    tone: "confidence",
  })

  return messages
}

/** The compact value strip: immediate work, quick wins, coverage, evidence state. */
export function valueStrip(report: StructuredAuditReport) {
  const actions = actionsOf(report)
  const evidence = evidenceStatus(report)

  return {
    immediate: actions.filter((a) => a.timing === "immediate").length,
    quickWins: actions.filter((a) => a.effort === "quick").length,
    coverage: `${evidence.assessed} of ${evidence.total}`,
    evidenceOk: evidence.withheld.length === 0,
    evidenceLabel: evidence.withheld.length === 0 ? "Complete" : "Re-audit required",
  }
}
