import { useMemo, useState, type ReactNode } from "react"

import { CategoryScoreHeader } from "@/components/audit/CategoryScoreHeader"
import { FindingCard } from "@/components/audit/FindingCard"
import { FindingDrawer } from "@/components/audit/FindingDrawer"
import { UnavailablePanel } from "@/components/audit/UnavailablePanel"
import { Card, CardContent } from "@/components/ui/card"
import { compactSeverityLabel, describeUnavailable, groupFindingsByTitle } from "@/lib/issueText"
import { cn } from "@/lib/utils"
import type { AuditCategory, CategoryResult, Severity } from "@/types/audit"

type SeverityFilter = "all" | Severity

// Neither Accessibility nor SEO currently produce "info"-severity findings —
// giving it a filter chip would always read 0 and add clutter, so it's left
// out here rather than guessed at.
const FILTER_SEVERITIES: Severity[] = ["critical", "high", "medium", "low"]

/** Turns a finding-group title into a stable DOM id the right-rail "in this
 * section" nav can scroll to — namespaced per category so e.g. Accessibility
 * and SEO groups never collide. */
export function findingGroupAnchorId(categoryId: string, title: string): string {
  return `${categoryId}-group-${title.toLowerCase().replace(/\s+/g, "-")}`
}

/**
 * Findings list following the Report list -> Open finding -> Review evidence
 * -> Apply remediation pattern: findings are grouped by check so e.g. 8 empty
 * buttons (or 5 images missing alt text) render as one scannable card instead
 * of many identical ones, a severity breakdown + filter row replaces a plain
 * summary sentence, and evidence/remediation only appear once a finding is
 * opened in the right-side drawer. Shared by Accessibility and SEO, the two
 * categories whose rule checks can legitimately fire more than once per page
 * (Performance's findings are each a distinct metric already, so it stays on
 * the plain CategoryCard).
 */
export function GroupedFindingsSection({
  id,
  title,
  icon,
  result,
  pageUrl,
}: {
  id: string
  title: string
  icon: ReactNode
  result: CategoryResult
  pageUrl: string
}) {
  const unavailable = result.score === null
  const [filter, setFilter] = useState<SeverityFilter>("all")
  const [openTitle, setOpenTitle] = useState<string | null>(null)
  const [reviewedTitles, setReviewedTitles] = useState<Set<string>>(new Set())

  const groups = useMemo(() => groupFindingsByTitle(result.recommendations), [result.recommendations])
  const totalCount = result.recommendations.length
  const severityCounts = useMemo(() => {
    const counts: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
    for (const rec of result.recommendations) counts[rec.severity] += 1
    return counts
  }, [result.recommendations])

  const filteredGroups = filter === "all" ? groups : groups.filter((group) => group.severity === filter)
  const openGroup = openTitle ? groups.find((group) => group.title === openTitle) : undefined

  function toggleReviewed(groupTitle: string) {
    setReviewedTitles((prev) => {
      const next = new Set(prev)
      if (next.has(groupTitle)) next.delete(groupTitle)
      else next.add(groupTitle)
      return next
    })
  }

  return (
    <Card id={id} className="scroll-mt-6 flex h-full flex-col break-inside-avoid rounded-[22px] p-8 shadow-none">
      <div className="flex items-center gap-2.5 font-display text-xl font-bold">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary">{icon}</span>
        {title}
      </div>

      <CardContent className="flex flex-1 flex-col p-0">
        {unavailable ? (
          <div className="mt-5">
            <UnavailablePanel {...describeUnavailable(result.category as AuditCategory, result.summary)} />
          </div>
        ) : (
          <>
            <div className="mt-5">
              <CategoryScoreHeader score={result.score} />
            </div>

            <div className="mt-4">
              <div className="font-display text-base font-bold">
                {totalCount} issue{totalCount === 1 ? "" : "s"} found
              </div>
              {totalCount > 0 && (
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
                  {FILTER_SEVERITIES.filter((severity) => severityCounts[severity] > 0).map((severity) => (
                    <span key={severity}>
                      {severityCounts[severity]} {compactSeverityLabel(severity)}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {totalCount > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter by severity">
                <FilterPill active={filter === "all"} onClick={() => setFilter("all")}>
                  All {totalCount}
                </FilterPill>
                {FILTER_SEVERITIES.map((severity) => (
                  <FilterPill key={severity} active={filter === severity} onClick={() => setFilter(severity)}>
                    {compactSeverityLabel(severity)} {severityCounts[severity]}
                  </FilterPill>
                ))}
              </div>
            )}

            {totalCount === 0 ? (
              <p className="mt-5 text-sm text-muted-foreground">
                Nice and clean — {title.toLowerCase()} is in great shape.
              </p>
            ) : filteredGroups.length === 0 ? (
              <p className="mt-5 text-sm text-muted-foreground">No {filter} issues.</p>
            ) : (
              <ul className="mt-5 flex flex-col gap-3">
                {filteredGroups.map((group) => (
                  <FindingCard
                    key={group.title}
                    id={findingGroupAnchorId(id, group.title)}
                    title={group.title}
                    severity={group.severity}
                    occurrences={group.occurrences}
                    reviewed={reviewedTitles.has(group.title)}
                    onOpen={() => setOpenTitle(group.title)}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>

      {openGroup && (
        <FindingDrawer
          title={openGroup.title}
          severity={openGroup.severity}
          occurrences={openGroup.occurrences}
          pageUrl={pageUrl}
          reviewed={reviewedTitles.has(openGroup.title)}
          categoryLabel={title}
          onToggleReviewed={() => toggleReviewed(openGroup.title)}
          onClose={() => setOpenTitle(null)}
        />
      )}
    </Card>
  )
}

function FilterPill({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex min-h-8 items-center rounded-full border px-3 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        active ? "border-transparent bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary"
      )}
    >
      {children}
    </button>
  )
}
