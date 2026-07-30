import { useState } from "react"
import { Image as ImageIcon, Maximize2, ThumbsDown, ThumbsUp, Wand2 } from "lucide-react"

import { CategoryScoreHeader } from "@/components/audit/CategoryScoreHeader"
import { InsightGroup } from "@/components/audit/InsightGroupList"
import { ScreenshotModal } from "@/components/audit/ScreenshotModal"
import { UnavailablePanel } from "@/components/audit/UnavailablePanel"
import { Card, CardContent } from "@/components/ui/card"
import { describeUnavailable } from "@/lib/issueText"
import { isVisualRawData } from "@/lib/rawData"
import type { AuditCategory, CategoryResult } from "@/types/audit"

/**
 * Visual Review section. No on-page screenshot preview/device frame (removed
 * per product decision — it kept needing rework and added visual clutter
 * without adding real information); instead a single "Open Full Screenshot"
 * action opens the real captured screenshot in ScreenshotModal on demand.
 * Screenshot capture and the Gemini vision call fail independently (see
 * backend/report.py), so this stays available even if the written analysis
 * isn't.
 */
export function VisualReviewCard({
  id,
  result,
  screenshotViewportBase64,
  screenshotFullPageBase64,
}: {
  id?: string
  result: CategoryResult
  screenshotViewportBase64: string | null
  screenshotFullPageBase64?: string | null
}) {
  const [modalSrc, setModalSrc] = useState<string | null>(null)
  const visualData = isVisualRawData(result.raw_data) ? result.raw_data : null
  const unavailable = result.score === null
  const viewportSrc = screenshotViewportBase64
    ? `data:image/png;base64,${screenshotViewportBase64}`
    : null
  const fullPageSrc = screenshotFullPageBase64
    ? `data:image/png;base64,${screenshotFullPageBase64}`
    : null
  // Prefer the full page capture (matches the button's "Full Screenshot"
  // label); fall back to the viewport capture if only that's available.
  const screenshotSrc = fullPageSrc ?? viewportSrc

  return (
    <Card id={id} className="scroll-mt-6 break-inside-avoid rounded-[22px] p-9 shadow-none">
      <div className="flex items-center justify-between gap-3 font-display text-xl font-bold">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary">
            <ImageIcon className="size-[17px]" />
          </span>
          Visual Review
        </div>
        {screenshotSrc && (
          <button
            type="button"
            onClick={() => setModalSrc(screenshotSrc)}
            className="flex min-h-11 items-center gap-1.5 rounded-full border px-4 text-[13px] font-semibold text-foreground/80 transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 print:hidden"
          >
            <Maximize2 className="size-3.5" />
            Open Full Screenshot
          </button>
        )}
      </div>

      {!unavailable && (
        <div className="mt-5 max-w-md">
          <CategoryScoreHeader score={result.score} size="md" />
        </div>
      )}
      {!unavailable && result.summary && (
        <p className="mt-3 text-[13px] text-muted-foreground">{result.summary}</p>
      )}

      <CardContent className="mt-6 p-0">
        <div className="flex flex-col gap-5">
          {unavailable ? (
            <UnavailablePanel
              {...describeUnavailable(result.category as AuditCategory, result.summary)}
            />
          ) : visualData ? (
            <>
              <InsightGroup
                id="visual-strengths"
                label="Strengths"
                icon={<ThumbsUp className="size-3.5 text-success" />}
                items={visualData.strengths}
                visibleCount={visualData.strengths.length}
              />
              <InsightGroup
                id="visual-weaknesses"
                label="Weaknesses"
                icon={<ThumbsDown className="size-3.5 text-destructive" />}
                items={visualData.weaknesses}
                visibleCount={visualData.weaknesses.length}
              />
              <InsightGroup
                id="visual-recommendations"
                label="Recommendations"
                icon={<Wand2 className="size-3.5 text-primary" />}
                items={visualData.recommendations}
                visibleCount={visualData.recommendations.length}
              />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Visual analysis isn't available for this audit.
            </p>
          )}
        </div>
      </CardContent>

      {modalSrc && (
        <ScreenshotModal
          src={modalSrc}
          alt="Screenshot of the audited page"
          onClose={() => setModalSrc(null)}
        />
      )}
    </Card>
  )
}
