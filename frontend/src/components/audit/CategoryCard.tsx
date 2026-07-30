import type { ReactNode } from "react"

import { CategoryScoreHeader } from "@/components/audit/CategoryScoreHeader"
import { RecommendationList } from "@/components/audit/RecommendationList"
import { UnavailablePanel } from "@/components/audit/UnavailablePanel"
import { Card, CardContent } from "@/components/ui/card"
import { describeUnavailable } from "@/lib/issueText"
import type { AuditCategory, CategoryResult } from "@/types/audit"

export function CategoryCard({
  id,
  title,
  icon,
  result,
  pageUrl,
}: {
  id?: string
  title: string
  icon: ReactNode
  result: CategoryResult
  pageUrl?: string | null
}) {
  const unavailable = result.score === null

  return (
    <Card
      id={id}
      className="scroll-mt-6 flex h-full flex-col break-inside-avoid rounded-[22px] p-8 shadow-none"
    >
      <div className="flex items-center gap-2.5 font-display text-xl font-bold">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary">
          {icon}
        </span>
        {title}
      </div>
      <CardContent className="flex flex-1 flex-col p-0">
        {unavailable ? (
          <div className="mt-5">
            <UnavailablePanel
              {...describeUnavailable(result.category as AuditCategory, result.summary)}
            />
          </div>
        ) : (
          <>
            <div className="mt-5">
              <CategoryScoreHeader score={result.score} />
            </div>

            {result.summary && <p className="mt-3 text-[13px] text-muted-foreground">{result.summary}</p>}

            <RecommendationList
              items={result.recommendations}
              pageUrl={pageUrl}
              emptyStateDetail={`Nice and clean — ${title.toLowerCase()} is in great shape.`}
              idPrefix={id}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}
