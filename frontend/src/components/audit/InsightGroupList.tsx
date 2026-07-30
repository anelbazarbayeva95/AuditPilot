import type { ReactNode } from "react"

import type { ConfidenceLevel } from "@/types/audit"

/** Shared shape of CopyInsight/VisualInsight — a dimension-tagged observation. */
interface DimensionInsight {
  dimension: string
  point: string
  confidence?: ConfidenceLevel | null
}

function formatDimension(dimension: string): string {
  return dimension
    .split("_")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ")
}

// Visual weight communicates how much scrutiny each level deserves: a "low"
// confidence call is a judgment call worth a second look, not a hard fact.
const CONFIDENCE_STYLE: Record<ConfidenceLevel, string> = {
  high: "bg-secondary text-foreground/70",
  medium: "border border-border text-muted-foreground",
  low: "border border-dashed border-border text-muted-foreground",
}

const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
}

/**
 * One labeled group of dimension-pill + text cards (Strengths/Weaknesses/
 * Recommendations), shared by CopyReviewCard and VisualReviewCard since
 * CopyInsight and VisualInsight are structurally identical.
 */
export function InsightGroup({
  id,
  label,
  icon,
  items,
  visibleCount,
}: {
  /** DOM id — lets the Results page's "in this section" rail jump straight to this group. */
  id?: string
  label: string
  icon: ReactNode
  items: DimensionInsight[]
  /** How many items to render — pass items.length to show everything. */
  visibleCount: number
}) {
  if (items.length === 0) {
    return null
  }
  const visible = items.slice(0, visibleCount)

  return (
    <div id={id} className="scroll-mt-24 flex flex-col gap-2.5">
      <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
        {icon}
        {label}
      </h3>
      <ul className="flex flex-col gap-2.5">
        {visible.map((item, index) => (
          <li key={index} className="rounded-xl border p-3.5 break-inside-avoid">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-fit rounded-full bg-secondary px-2.5 py-1 text-[11px] font-semibold">
                {formatDimension(item.dimension)}
              </span>
              {item.confidence && (
                <span
                  title="Gemini's self-reported certainty in this specific observation"
                  className={`w-fit rounded-full px-2.5 py-1 text-[11px] font-medium ${CONFIDENCE_STYLE[item.confidence]}`}
                >
                  {CONFIDENCE_LABEL[item.confidence]}
                </span>
              )}
            </div>
            <p className="mt-2 text-[13px] text-muted-foreground">{item.point}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
