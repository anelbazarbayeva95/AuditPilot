import { Check } from "lucide-react"

import { IssueItem } from "@/components/audit/IssueItem"
import type { Recommendation } from "@/types/audit"

export function RecommendationList({
  items,
  pageUrl,
  emptyStateDetail,
  idPrefix,
}: {
  items: Recommendation[]
  pageUrl?: string | null
  /** e.g. "SEO is in great shape." — shown under "No issues found" when this category is clean. */
  emptyStateDetail?: string
  /** Namespaces each issue's DOM id (e.g. "accessibility" -> "accessibility-1") so the
   * Results page's "in this section" rail can jump straight to a specific issue. */
  idPrefix?: string
}) {
  if (items.length === 0) {
    return (
      <div className="mt-2.5 flex flex-col items-center gap-3 rounded-2xl border border-dashed p-7 text-center">
        <span className="flex size-11 items-center justify-center rounded-full bg-quickfix-bg">
          <Check className="size-[22px] text-quickfix-text" strokeWidth={2.6} />
        </span>
        <div className="font-display text-xl font-bold">No issues found</div>
        <p className="text-[13px] text-muted-foreground">
          {emptyStateDetail ?? "Nice and clean — no issues detected here."}
        </p>
      </div>
    )
  }

  return (
    <div className="mt-5 flex flex-col gap-2.5">
      <ul className="flex flex-col gap-3">
        {items.map((item, index) => (
          <IssueItem
            key={index}
            id={idPrefix ? `${idPrefix}-${index + 1}` : undefined}
            title={item.title}
            description={item.description}
            severity={item.severity}
            pageUrl={pageUrl}
            context={item.context}
            section={item.section}
          />
        ))}
      </ul>
    </div>
  )
}
