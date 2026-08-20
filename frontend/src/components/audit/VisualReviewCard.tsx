import { useState } from "react"
import { AlertTriangle, Image as ImageIcon, Maximize2, ThumbsDown, ThumbsUp, Wand2 } from "lucide-react"

import { CategoryScoreHeader } from "@/components/audit/CategoryScoreHeader"
import { InsightGroup } from "@/components/audit/InsightGroupList"
import { ScreenshotModal } from "@/components/audit/ScreenshotModal"
import { UnavailablePanel } from "@/components/audit/UnavailablePanel"
import { Card, CardContent } from "@/components/ui/card"
import { describeUnavailable } from "@/lib/issueText"
import { isVisualRawData } from "@/lib/rawData"
import type { AuditCategory, CategoryResult, ScreenshotQuality } from "@/types/audit"

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
  screenshotQuality,
}: {
  id?: string
  result: CategoryResult
  screenshotViewportBase64: string | null
  screenshotFullPageBase64?: string | null
  /** Measured usability of the capture. A "degraded" capture is documented as a
   *  failed render, never presented as the page. */
  screenshotQuality?: ScreenshotQuality | null
}) {
  const [modalSrc, setModalSrc] = useState<string | null>(null)
  const visualData = isVisualRawData(result.raw_data) ? result.raw_data : null
  const unavailable = result.score === null
  const withheld = result.score_status === "insufficient_evidence"
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
        {screenshotSrc && !withheld && (
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

      {/* Refusing to assess a bad capture is the product's differentiator, so
          it is stated as a decision with its measurements — not left looking
          like a missing section or, worse, a rendering fault in this page. */}
      {withheld && (
        <div className="mt-5 rounded-2xl bg-withheld-bg p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-withheld" aria-hidden="true" />
            <div>
              <div className="font-display text-[15px] font-bold">
                Assessment withheld — capture did not meet the evidence threshold
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-foreground/75">
                {screenshotQuality?.reason ??
                  "The page did not finish rendering before capture, so there was nothing reliable to assess."}{" "}
                No visual score was produced and this category was excluded from the overall score.
                Re-run the audit to complete coverage.
              </p>
              {screenshotQuality && (
                <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-[11px] text-muted-foreground">
                  {screenshotQuality.dominant_color_pct != null && (
                    <div>
                      <dt className="inline font-semibold">Single flat color: </dt>
                      <dd className="inline tabular-nums">
                        {Math.round(screenshotQuality.dominant_color_pct)}%
                      </dd>
                    </div>
                  )}
                  {screenshotQuality.uniform_row_pct != null && (
                    <div>
                      <dt className="inline font-semibold">Rows without variation: </dt>
                      <dd className="inline tabular-nums">
                        {Math.round(screenshotQuality.uniform_row_pct)}%
                      </dd>
                    </div>
                  )}
                  {screenshotQuality.content_top_pct != null && (
                    <div>
                      <dt className="inline font-semibold">First content at: </dt>
                      <dd className="inline tabular-nums">
                        {Math.round(screenshotQuality.content_top_pct)}% down
                      </dd>
                    </div>
                  )}
                </dl>
              )}
              {screenshotSrc && (
                <button
                  type="button"
                  onClick={() => setModalSrc(screenshotSrc)}
                  className="mt-3 cursor-pointer text-[13px] font-semibold text-link underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
                >
                  View the failed capture (kept as diagnostic evidence)
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <CardContent className="mt-6 p-0">
        <div className="flex flex-col gap-5">
          {withheld ? null : unavailable ? (
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
