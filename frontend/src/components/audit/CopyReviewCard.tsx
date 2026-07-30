import { MessageSquareText, ThumbsDown, ThumbsUp, Wand2 } from "lucide-react"

import { CategoryScoreHeader } from "@/components/audit/CategoryScoreHeader"
import { InsightGroup } from "@/components/audit/InsightGroupList"
import { UnavailablePanel } from "@/components/audit/UnavailablePanel"
import { Card, CardContent } from "@/components/ui/card"
import { describeUnavailable } from "@/lib/issueText"
import { isCopyRawData } from "@/lib/rawData"
import type { AuditCategory, CategoryResult } from "@/types/audit"

export function CopyReviewCard({ id, result }: { id?: string; result: CategoryResult }) {
  const copyData = isCopyRawData(result.raw_data) ? result.raw_data : null
  const unavailable = result.score === null

  const totalCount = copyData
    ? copyData.strengths.length + copyData.weaknesses.length + copyData.recommendations.length
    : 0

  return (
    <Card id={id} className="scroll-mt-6 flex h-full flex-col break-inside-avoid rounded-[22px] p-8 shadow-none">
      <div className="flex items-center gap-2.5 font-display text-xl font-bold">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary">
          <MessageSquareText className="size-[17px]" />
        </span>
        Copy Review
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

            {copyData && totalCount > 0 ? (
              <div className="mt-5 flex flex-col gap-5">
                <InsightGroup
                  id="copy-strengths"
                  label="Strengths"
                  icon={<ThumbsUp className="size-3.5 text-success" />}
                  items={copyData.strengths}
                  visibleCount={copyData.strengths.length}
                />
                <InsightGroup
                  id="copy-weaknesses"
                  label="Weaknesses"
                  icon={<ThumbsDown className="size-3.5 text-destructive" />}
                  items={copyData.weaknesses}
                  visibleCount={copyData.weaknesses.length}
                />
                <InsightGroup
                  id="copy-recommendations"
                  label="Recommendations"
                  icon={<Wand2 className="size-3.5 text-primary" />}
                  items={copyData.recommendations}
                  visibleCount={copyData.recommendations.length}
                />
              </div>
            ) : (
              <p className="mt-5 text-sm text-muted-foreground">
                Copy analysis isn't available for this audit.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
