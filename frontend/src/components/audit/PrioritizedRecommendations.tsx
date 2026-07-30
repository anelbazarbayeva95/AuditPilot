import { IssueItem } from "@/components/audit/IssueItem"
import { Card, CardContent } from "@/components/ui/card"
import { dedupeRecommendations } from "@/lib/issueText"
import type { Recommendation } from "@/types/audit"

const CATEGORY_LABELS: Record<string, string> = {
  accessibility: "Accessibility",
  seo: "SEO",
  performance: "Performance",
  copy: "Copy",
  visual: "Visual",
}

/**
 * The merged, cross-category priority list. The same underlying issue often
 * gets flagged by more than one agent (e.g. "Multiple H1" from both
 * Accessibility and SEO) — dedupeRecommendations() merges those into one
 * numbered card listing every category it affects, ordered by severity and
 * then by how quick the fix is, so the first few items are genuinely "what
 * to do next" rather than a raw findings dump. Now that this list gets its
 * own dedicated page in the Results "Docs Layout", everything is shown at
 * once rather than capped behind a "show more" toggle.
 */
export function PrioritizedRecommendations({
  items,
  pageUrl,
}: {
  items: Recommendation[]
  pageUrl?: string | null
}) {
  const issues = dedupeRecommendations(items)

  return (
    <Card className="rounded-[22px] p-10 shadow-none">
      <div className="font-display text-[28px] font-bold tracking-tight">Prioritized Action List</div>
      <CardContent className="mt-6 p-0">
        {issues.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No action items — everything looks good.
          </p>
        ) : (
          <ol className="flex flex-col gap-3.5">
            {issues.map((issue, index) => (
              <IssueItem
                key={index}
                id={`action-${index + 1}`}
                ordinal={index + 1}
                title={issue.title}
                description={issue.description}
                severity={issue.severity}
                categoryLabels={issue.categories.map((category) => CATEGORY_LABELS[category] ?? category)}
                pageUrl={pageUrl}
                context={issue.context}
                section={issue.section}
              />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}
