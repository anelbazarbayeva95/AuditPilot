import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import {
  formatScore,
  getScoreBand,
  scoreBandIndicatorClass,
  scoreBandLabel,
  scoreBandTextClass,
} from "@/lib/score"

export function OverallScoreCard({
  score,
  categoryScores,
}: {
  score: number | null
  /** report.summary.category_scores — used only to report how many categories actually completed. */
  categoryScores?: Record<string, number | null>
}) {
  const band = getScoreBand(score)
  const entries = categoryScores ? Object.values(categoryScores) : []
  const total = entries.length
  const completed = entries.filter((value) => value !== null).length
  const allComplete = total === 0 || completed === total
  const missing = total - completed

  return (
    <Card className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="text-base font-medium text-muted-foreground">
          Overall Score
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
          <div
            className={`text-6xl font-semibold tabular-nums ${scoreBandTextClass[band]}`}
          >
            {formatScore(score)}
            <span className="text-2xl text-muted-foreground">/100</span>
          </div>
          <div className="flex w-full flex-1 flex-col gap-2">
            <div className="flex flex-col gap-1 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span className="font-medium">{scoreBandLabel[band]}</span>
              <span className="text-muted-foreground">
                {allComplete
                  ? "Mean of Accessibility, SEO, Performance, Copy & Visual"
                  : `Score based on ${completed} of ${total} completed categories`}
              </span>
            </div>
            <Progress
              value={score ?? 0}
              indicatorClassName={scoreBandIndicatorClass[band]}
              className="h-3"
            />
            {!allComplete && (
              <p className="text-xs text-muted-foreground">
                {missing} categor{missing === 1 ? "y" : "ies"} unavailable and not reflected in this score.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
