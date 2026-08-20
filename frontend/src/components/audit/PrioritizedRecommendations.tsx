import { Info } from "lucide-react"

import { IssueItem } from "@/components/audit/IssueItem"
import { Card, CardContent } from "@/components/ui/card"
import { actionsOf, categoryLabel } from "@/lib/summary"
import type { StructuredAuditReport } from "@/types/audit"

/**
 * The cross-category priority list — a work list, not a findings dump.
 *
 * Consolidation happens in the backend (`actions.py`) so the PDF and the UI
 * can't disagree about what the plan is: findings that share one fix become
 * one action naming every category it benefits, and outcome metrics like the
 * Lighthouse score are held out as success measures rather than listed as
 * tasks. "Improve the Lighthouse score" tells nobody what to change; the
 * render-blocking file it names does.
 */
export function PrioritizedRecommendations({
  report,
  pageUrl,
}: {
  report: StructuredAuditReport
  pageUrl?: string | null
}) {
  const actions = actionsOf(report)
  const kpiNotes = report.kpi_notes ?? []

  return (
    <Card className="rounded-[22px] p-10 shadow-none">
      <div className="font-display text-[28px] font-bold tracking-tight">Prioritized Action List</div>
      <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
        Each entry is one unit of work, ranked by when it should be scheduled. Where a single fix
        resolves findings in more than one category, it appears once and names them all.
      </p>

      <CardContent className="mt-6 p-0">
        {actions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No action items — everything looks good.</p>
        ) : (
          <ol className="flex flex-col gap-3.5">
            {actions.map((action, index) => (
              <IssueItem
                key={action.key}
                id={`action-${index + 1}`}
                ordinal={index + 1}
                title={action.title}
                description={action.description}
                severity={action.severity}
                categoryLabels={action.categories.map(categoryLabel)}
                pageUrl={pageUrl}
                findingsResolved={action.findings_resolved}
                standard={action.primary_standard}
                estimatedSaving={action.estimated_saving}
                timing={action.timing}
                effort={action.effort}
                owner={action.owner}
                authored
              />
            ))}
          </ol>
        )}

        {kpiNotes.length > 0 && (
          <div className="mt-6 flex items-start gap-3 rounded-2xl bg-measured-bg p-4">
            <Info className="mt-0.5 size-4 shrink-0 text-measured" aria-hidden="true" />
            <div className="text-[13px] leading-relaxed text-foreground/80">
              <span className="font-semibold">How you'll know it worked.</span>
              <ul className="mt-1 flex flex-col gap-1">
                {kpiNotes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
