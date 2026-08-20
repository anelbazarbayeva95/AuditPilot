import { AlertTriangle, Check, Gauge, ShieldCheck } from "lucide-react"

import { EFFORT_LABEL, type EffortTier } from "@/lib/issueText"
import { isCopyRawData, isVisualRawData } from "@/lib/rawData"
import {
  formatScore,
  getScoreBand,
  SCORE_SCALE,
  scoreBandIndicatorClass,
  scoreBandLabel,
} from "@/lib/score"
import {
  actionsOf,
  categoryLabel,
  evidenceStatus,
  keyMessages,
  valueStrip,
  type KeyMessage,
} from "@/lib/summary"
import type { StructuredAuditReport } from "@/types/audit"

const EFFORT_ORDER: EffortTier[] = ["quick", "moderate", "involved"]

/** "1 quick win" / "3 quick wins" — never "3 quick win". */
function effortPhrase(tier: EffortTier, count: number): string {
  const label = EFFORT_LABEL[tier].toLowerCase()
  if (count === 1) return label
  return tier === "quick" ? "quick wins" : label
}

/** Up to a handful of genuine, data-backed positives — not filler. */
function collectStrengths(report: StructuredAuditReport): string[] {
  const strengths: string[] = []

  const copyData = isCopyRawData(report.copy.raw_data) ? report.copy.raw_data : null
  if (copyData && copyData.strengths.length > 0) {
    strengths.push(copyData.strengths[0].point)
  }

  // Only from a category that was actually assessed — a withheld category has
  // no strengths to report, and saying otherwise would contradict the
  // evidence notice directly above it.
  const visualAssessed = (report.visual.score_status ?? "scored") === "scored"
  const visualData = isVisualRawData(report.visual.raw_data) ? report.visual.raw_data : null
  if (visualAssessed && visualData && visualData.strengths.length > 0) {
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

const MESSAGE_ICON: Record<KeyMessage["tone"], typeof AlertTriangle> = {
  risk: AlertTriangle,
  opportunity: Gauge,
  confidence: ShieldCheck,
}

/** Icon tint per message, drawn from the semantic token set — never colour alone:
 *  each message also carries a written label. */
const MESSAGE_TONE_CLASS: Record<KeyMessage["tone"], string> = {
  risk: "bg-severity-high-bg text-severity-high",
  opportunity: "bg-measured-bg text-measured",
  confidence: "bg-withheld-bg text-withheld",
}

/**
 * The decision-making layer at the top of the report.
 *
 * It leads with what the reader now knows and what to do about it — primary
 * risk, largest measured opportunity, how far the evidence goes — rather than
 * with what the scanner found. The counts and findings below are the support
 * for those three sentences, not a substitute for them.
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

  const actions = actionsOf(report)
  const topAction = actions[0]
  const restActions = actions.slice(1, 3)
  const messages = keyMessages(report)
  const strip = valueStrip(report)
  const evidence = evidenceStatus(report)

  const highSeverityCount =
    (report.summary.issue_counts.critical ?? 0) + (report.summary.issue_counts.high ?? 0)

  const effortCounts = actions.reduce(
    (acc, action) => {
      const tier: EffortTier =
        action.effort === "quick" ? "quick" : action.effort === "involved" ? "involved" : "moderate"
      acc[tier] += 1
      return acc
    },
    { quick: 0, moderate: 0, involved: 0 } as Record<EffortTier, number>
  )

  const strengths = collectStrengths(report)

  return (
    <div className="break-inside-avoid">
      <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
        Audit report · {hostnameOf(url)}
      </div>
      <h1 className="mt-2.5 font-display text-4xl font-bold tracking-tight sm:text-5xl">
        Executive Summary
      </h1>

      <div
        id="summary-health"
        className="mt-7 grid scroll-mt-24 grid-cols-1 items-stretch gap-5 lg:grid-cols-[1fr_300px]"
      >
        <div className="flex flex-col justify-between rounded-[18px] border p-7">
          <span className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Overall health
          </span>
          <div className="mt-3 flex items-end gap-4">
            <span className="font-display text-7xl leading-[0.85] font-bold tracking-tight tabular-nums sm:text-8xl">
              {formatScore(score)}
            </span>
            <span className="pb-2 text-sm text-muted-foreground">
              /100 ·{" "}
              <span className="font-semibold text-foreground">{scoreBandLabel[band]}</span>
            </span>
          </div>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div
              className={`h-full rounded-full ${scoreBandIndicatorClass[band]}`}
              style={{ width: `${score ?? 0}%` }}
            />
          </div>
          {/* The scale is published beside the score so the band is a stated
              convention rather than something the reader has to infer. */}
          <p className="mt-2.5 text-[11px] text-muted-foreground">{SCORE_SCALE}</p>
          {report.summary.score_explanation && (
            <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
              {report.summary.score_explanation}
            </p>
          )}
        </div>

        <div className="flex flex-col justify-between rounded-[18px] bg-ink p-6">
          <span className="text-[11px] font-semibold tracking-[0.15em] text-ink-muted uppercase">
            At a glance
          </span>
          <div className="mt-4 grid grid-cols-2 gap-3.5">
            <div>
              <div className="font-display text-3xl leading-none font-bold text-ink-foreground tabular-nums">
                {strip.immediate}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">Immediate</div>
            </div>
            <div>
              <div className="font-display text-3xl leading-none font-bold text-primary tabular-nums">
                {strip.quickWins}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">Quick wins</div>
            </div>
            <div>
              <div className="font-display text-3xl leading-none font-bold text-ink-foreground tabular-nums">
                {strip.coverage}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">Categories assessed</div>
            </div>
            <div>
              <div
                className={`font-display text-3xl leading-none font-bold tabular-nums ${
                  highSeverityCount > 0 ? "text-[var(--status-poor-on-dark)]" : "text-ink-foreground"
                }`}
              >
                {highSeverityCount}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">High severity</div>
            </div>
          </div>
        </div>
      </div>

      {/* What the reader now knows, before any finding detail. */}
      <div id="summary-messages" className="mt-5 scroll-mt-24 rounded-[18px] border">
        {messages.map((message, index) => {
          const Icon = MESSAGE_ICON[message.tone]
          return (
            <div
              key={message.label}
              className={`flex items-start gap-3.5 p-5 ${index > 0 ? "border-t" : ""}`}
            >
              <span
                className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[10px] ${
                  MESSAGE_TONE_CLASS[message.tone]
                }`}
              >
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <div>
                <div className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                  {message.label}
                </div>
                <p className="mt-1 text-base leading-relaxed text-foreground/85">{message.body}</p>
              </div>
            </div>
          )
        })}
      </div>

      {/* Knowing when not to make a claim is the product's differentiator, so
          a withheld category is stated plainly rather than left as a gap. */}
      {evidence.withheld.length > 0 && (
        <div className="mt-4 flex items-start gap-3 rounded-2xl bg-withheld-bg p-4">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-withheld" aria-hidden="true" />
          <p className="text-[13px] leading-relaxed text-foreground/80">
            <span className="font-semibold">Evidence withheld.</span>{" "}
            {evidence.withheld.map((w) => `${w.label} (${w.reason})`).join(", ")} — excluded from the
            overall score rather than assessed on unreliable evidence. Re-run the audit to complete
            coverage.
          </p>
        </div>
      )}

      {topAction && (
        <div
          id="summary-top-issue"
          className="relative mt-5 flex scroll-mt-24 flex-col items-start gap-5 overflow-hidden rounded-2xl bg-ink p-5 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="absolute inset-y-0 left-0 w-[5px] bg-severity-high" />
          <div className="relative">
            <span className="text-[11px] font-semibold tracking-[0.15em] text-ink-muted uppercase">
              Start here
            </span>
            <div className="mt-2 font-display text-xl font-bold text-ink-foreground">
              {topAction.title}
            </div>
            <div className="mt-1 text-[13px] text-ink-muted">
              {topAction.categories.map(categoryLabel).join(", ")}
              {topAction.findings_resolved > 1 && ` · closes ${topAction.findings_resolved} findings`}
              {topAction.effort && ` · ${EFFORT_LABEL[topAction.effort as EffortTier] ?? topAction.effort}`}
            </div>
          </div>
          <button
            type="button"
            onClick={onViewActions}
            className="relative shrink-0 cursor-pointer rounded-full bg-primary px-5 py-2.5 text-[13px] font-semibold whitespace-nowrap text-primary-foreground transition duration-200 hover:brightness-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            View action list ↓
          </button>
        </div>
      )}

      <div
        id="summary-also-fixing"
        className="mt-8 grid scroll-mt-24 grid-cols-1 gap-10 border-t pt-7 sm:grid-cols-2"
      >
        <div>
          <h2 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Then
          </h2>
          {restActions.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">Nothing else urgent right now.</p>
          ) : (
            <div className="mt-4 flex flex-col gap-3">
              {restActions.map((action, index) => (
                <div key={action.key} className="flex items-center gap-3">
                  <span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground tabular-nums">
                    {index + 2}
                  </span>
                  <span className="text-base text-foreground/80">{action.title}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <h2 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Estimated fix effort
          </h2>
          {actions.length === 0 ? (
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
                  {effortCounts[tier]} {effortPhrase(tier, effortCounts[tier])}
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
                  <Check className="size-3 text-primary-foreground" strokeWidth={3} aria-hidden="true" />
                </span>
                {strength}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3.5 text-sm text-muted-foreground">
            Not enough data yet to highlight strengths.
          </p>
        )}
      </div>
    </div>
  )
}
