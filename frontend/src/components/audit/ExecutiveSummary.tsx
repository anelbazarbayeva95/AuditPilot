import { Check } from "lucide-react"

import { dedupeRecommendations, EFFORT_LABEL, effortFor, type EffortTier } from "@/lib/issueText"
import { isCopyRawData, isVisualRawData } from "@/lib/rawData"
import { formatScore, getScoreBand, scoreBandIndicatorClass, scoreBandLabel } from "@/lib/score"
import type { StructuredAuditReport } from "@/types/audit"

const EFFORT_ORDER: EffortTier[] = ["quick", "moderate", "involved"]

/** Up to a handful of genuine, data-backed positives — not filler. */
function collectStrengths(report: StructuredAuditReport): string[] {
  const strengths: string[] = []

  const copyData = isCopyRawData(report.copy.raw_data) ? report.copy.raw_data : null
  if (copyData && copyData.strengths.length > 0) {
    strengths.push(copyData.strengths[0].point)
  }

  const visualData = isVisualRawData(report.visual.raw_data) ? report.visual.raw_data : null
  if (visualData && visualData.strengths.length > 0) {
    strengths.push(visualData.strengths[0].point)
  }

  const ruleCategories: Array<[string, number | null]> = [
    ["Accessibility", report.accessibility.score],
    ["SEO", report.seo.score],
    ["Performance", report.performance.score],
  ]
  for (const [label, score] of ruleCategories) {
    if (score !== null && score >= 85) {
      strengths.push(`${label} is in great shape (${Math.round(score)}/100).`)
    }
  }

  return strengths.slice(0, 4)
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

/** Left-accent-stripe / numbered-circle color for a severity, on the dark ink surface. */
function severityAccentClass(severity: string): string {
  if (severity === "critical" || severity === "high") return "bg-destructive"
  if (severity === "medium") return "bg-warning"
  return "bg-white/25"
}

/**
 * The decision-making layer at the top of the report ("4A — Sidebar
 * Console" direction): overall health + at-a-glance counts, the single
 * highest-priority issue spotlighted, then effort/strengths context.
 * Everything here is derived from the same report data shown in more
 * detail further down the page.
 */
export function ExecutiveSummary({
  report,
  url,
  onViewActions,
}: {
  report: StructuredAuditReport
  url: string
  /** Docs-layout Results page has no continuous scroll anymore — "View action
   *  list" switches the active section instead of jumping to an anchor. */
  onViewActions: () => void
}) {
  const { overall_score: score } = report.summary
  const band = getScoreBand(score)

  const dedupedIssues = dedupeRecommendations(report.recommendations)
  const topIssue = dedupedIssues[0]
  const restIssues = dedupedIssues.slice(1, 3)

  const highSeverityCount =
    (report.summary.issue_counts.critical ?? 0) + (report.summary.issue_counts.high ?? 0)
  const quickFixCount = dedupedIssues.filter((issue) => effortFor(issue.title) === "quick").length

  const effortCounts = dedupedIssues.reduce(
    (acc, issue) => {
      acc[effortFor(issue.title)] += 1
      return acc
    },
    { quick: 0, moderate: 0, involved: 0 } as Record<EffortTier, number>
  )

  const analyzedCount = Object.values(report.summary.category_scores).filter((s) => s !== null).length
  const strengths = collectStrengths(report)

  return (
    <div className="break-inside-avoid">
        <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
          Audit report · {hostnameOf(url)}
        </div>
        <h1 className="mt-2.5 font-display text-4xl font-bold tracking-tight sm:text-5xl">Executive Summary</h1>

        <div id="summary-health" className="mt-7 grid scroll-mt-24 grid-cols-1 items-stretch gap-5 lg:grid-cols-[1fr_300px]">
          <div className="flex flex-col justify-between rounded-[18px] border p-7">
            <span className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Overall health
            </span>
            <div className="mt-3 flex items-end gap-4">
              <span className="font-display text-7xl leading-[0.85] font-bold tracking-tight sm:text-8xl">
                {formatScore(score)}
              </span>
              <span className="pb-2 text-sm text-muted-foreground">/100 · {scoreBandLabel[band]}</span>
            </div>
            <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-secondary">
              <div
                className={`h-full rounded-full ${scoreBandIndicatorClass[band]}`}
                style={{ width: `${score ?? 0}%` }}
              />
            </div>
            <p className="mt-4 text-base text-foreground/70">
              {analyzedCount} of 5 categories analyzed.{" "}
              {topIssue ? `Top priority: ${topIssue.title}.` : "No outstanding issues found."}
            </p>
          </div>

          <div className="flex flex-col justify-between rounded-[18px] bg-ink p-6">
            <span className="text-[11px] font-semibold tracking-[0.15em] text-ink-muted uppercase">
              At a glance
            </span>
            <div className="mt-4 grid grid-cols-2 gap-3.5">
              <div>
                <div className="font-display text-3xl leading-none font-bold text-ink-foreground">
                  {report.recommendations.length}
                </div>
                <div className="mt-1 text-[11px] text-ink-muted">Issues</div>
              </div>
              <div>
                <div className="font-display text-3xl leading-none font-bold text-ink-foreground">
                  {dedupedIssues.length}
                </div>
                <div className="mt-1 text-[11px] text-ink-muted">Actions</div>
              </div>
              <div>
                <div className="font-display text-3xl leading-none font-bold text-primary">{quickFixCount}</div>
                <div className="mt-1 text-[11px] text-ink-muted">Quick wins</div>
              </div>
              <div>
                <div className="font-display text-3xl leading-none font-bold text-[var(--status-poor-on-dark)]">
                  {highSeverityCount}
                </div>
                <div className="mt-1 text-[11px] text-ink-muted">High sev.</div>
              </div>
            </div>
          </div>
        </div>

        {topIssue && (
          <div
            id="summary-top-issue"
            className="relative mt-5 flex scroll-mt-24 flex-col items-start gap-5 overflow-hidden rounded-2xl bg-ink p-5 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className={`absolute inset-y-0 left-0 w-[5px] ${severityAccentClass(topIssue.severity)}`} />
            <div className="relative">
              <span className="text-[11px] font-semibold tracking-[0.15em] text-ink-muted uppercase">
                Top issue
              </span>
              <div className="mt-2 font-display text-xl font-bold text-ink-foreground">{topIssue.title}</div>
              <div className="mt-1 text-[13px] text-ink-muted">
                {topIssue.categories[0]} · {topIssue.severity} impact
              </div>
            </div>
            <button
              type="button"
              onClick={onViewActions}
              className="relative shrink-0 rounded-full bg-primary px-5 py-2.5 text-[13px] font-semibold whitespace-nowrap text-primary-foreground transition hover:brightness-105"
            >
              View action list ↓
            </button>
          </div>
        )}

        <div id="summary-also-fixing" className="mt-8 grid scroll-mt-24 grid-cols-1 gap-10 border-t pt-7 sm:grid-cols-2">
          <div>
            <h2 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Also worth fixing
            </h2>
            {restIssues.length === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">Nothing else urgent right now.</p>
            ) : (
              <div className="mt-4 flex flex-col gap-3">
                {restIssues.map((issue, index) => (
                  <div key={index} className="flex items-center gap-3">
                    <span
                      className={`flex size-[22px] shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${severityAccentClass(
                        issue.severity
                      )}`}
                    >
                      {index + 2}
                    </span>
                    <span className="text-base text-foreground/80">{issue.title}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h2 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Estimated fix effort
            </h2>
            {dedupedIssues.length === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">Nothing to fix right now.</p>
            ) : (
              <div className="mt-4 flex flex-wrap gap-2.5">
                {EFFORT_ORDER.filter((tier) => effortCounts[tier] > 0).map((tier) => (
                  <span
                    key={tier}
                    className={`rounded-full px-4 py-1.5 text-[13px] font-semibold ${
                      tier === "quick"
                        ? "bg-quickfix-bg text-quickfix-text"
                        : "bg-secondary text-secondary-foreground/80"
                    }`}
                  >
                    {effortCounts[tier]} {EFFORT_LABEL[tier].toLowerCase()}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div id="summary-strengths" className="mt-7 scroll-mt-24 border-t pt-6">
          <h2 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Key strengths
          </h2>
          {strengths.length > 0 ? (
            <div className="mt-3.5 flex flex-col gap-2.5">
              {strengths.map((strength, index) => (
                <div key={index} className="flex items-start gap-2.5 text-base text-foreground/80">
                  <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-[6px] bg-primary">
                    <Check className="size-3 text-primary-foreground" strokeWidth={3} />
                  </span>
                  {strength}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3.5 text-sm text-muted-foreground">Not enough data yet to highlight strengths.</p>
          )}
        </div>
    </div>
  )
}
