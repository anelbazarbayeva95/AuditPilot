import { Progress } from "@/components/ui/progress"
import {
  formatScore,
  getScoreBand,
  scoreBandIndicatorClass,
  scoreBandLabel,
  scoreBandTextClass,
} from "@/lib/score"

/** Score number + progress bar, reused at the top of each category card. */
export function CategoryScoreHeader({ score, size = "lg" }: { score: number | null; size?: "lg" | "md" }) {
  const band = getScoreBand(score)

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <span
          className={`font-display font-bold tracking-tight tabular-nums ${size === "lg" ? "text-5xl" : "text-4xl"}`}
        >
          {formatScore(score)}
          <span className="text-sm font-normal text-muted-foreground">/100</span>
        </span>
        <span className={`text-[13px] font-semibold ${scoreBandTextClass[band]}`}>{scoreBandLabel[band]}</span>
      </div>
      <Progress
        value={score ?? 0}
        className="h-[5px] bg-secondary"
        indicatorClassName={scoreBandIndicatorClass[band]}
      />
    </div>
  )
}
