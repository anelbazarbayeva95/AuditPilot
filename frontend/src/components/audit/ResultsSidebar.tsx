import { formatScore, getScoreBand, scoreBandTextClass } from "@/lib/score"
import type { StructuredAuditReport } from "@/types/audit"

/** Every top-level "page" of the Results Docs Layout — exactly one renders at a time. */
export type SectionId =
  | "summary"
  | "visual"
  | "accessibility"
  | "seo"
  | "performance"
  | "copy"
  | "charts"
  | "actions"
  | "methodology"

interface NavItemDef {
  id: SectionId
  label: string
  /** Category ids that have a real score to show next to the label. */
  scoreKey?: "visual" | "accessibility" | "seo" | "performance" | "copy"
}

// Executive Summary first, then the cross-category Action list as the
// primary decision-making section (right after the summary rather than
// buried behind five category deep-dives) — per-category detail pages follow
// for whoever wants to dig into a specific area, then Charts as the
// most-zoomed-out view.
export const SECTION_ORDER: NavItemDef[] = [
  { id: "summary", label: "Executive Summary" },
  { id: "actions", label: "Action list" },
  { id: "visual", label: "Visual", scoreKey: "visual" },
  { id: "accessibility", label: "Accessibility", scoreKey: "accessibility" },
  { id: "seo", label: "SEO", scoreKey: "seo" },
  { id: "performance", label: "Performance", scoreKey: "performance" },
  { id: "copy", label: "Copy", scoreKey: "copy" },
  { id: "charts", label: "Charts" },
  // Last, but present: a score a reader cannot reproduce is an assertion.
  { id: "methodology", label: "Methodology" },
]

/** Scrolls to a sub-block within the currently-active section — used by the
 *  right "in this section" rail. A JS scroll rather than a native `<a href>`
 *  jump, since plain hash-link clicks have previously been intercepted as a
 *  full navigation in some embedding contexts. */
export function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })
}

/**
 * Left nav rail for the Results "Docs Layout": clicking a row switches which
 * section is mounted in the center column (not a scroll-spy over one long
 * page — only the active section's content exists in the DOM at a time).
 */
export function ResultsSidebar({
  report,
  active,
  onSelect,
}: {
  report: StructuredAuditReport
  active: SectionId
  onSelect: (id: SectionId) => void
}) {
  const overall = report.summary.overall_score

  return (
    <aside className="flex flex-col gap-1 border-b px-4 py-4 md:sticky md:top-0 md:h-svh md:flex-col md:border-r md:border-b-0 md:px-5 md:py-8 md:self-start md:overflow-y-auto print:hidden">
      <div className="mb-1.5 px-1 text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase md:mb-3">
        Report
      </div>
      <nav className="flex flex-row gap-1 overflow-x-auto md:flex-col md:overflow-visible">
        {SECTION_ORDER.map(({ id, label, scoreKey }) => {
          const isActive = active === id
          const score = scoreKey ? (report.summary.category_scores[scoreKey] ?? null) : null
          const band = scoreKey ? getScoreBand(score) : null
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelect(id)}
              className={`flex shrink-0 items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-[13px] transition-colors hover:bg-secondary ${
                isActive ? "bg-secondary font-semibold text-foreground" : "text-foreground/70"
              }`}
            >
              <span className="whitespace-nowrap">{label}</span>
              {scoreKey && (
                <span className={`font-display text-sm font-bold ${band ? scoreBandTextClass[band] : ""}`}>
                  {formatScore(score)}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      <div className="mt-auto hidden pt-5 md:block">
        <div className="border-t pt-4">
          <div className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">Overall</div>
          <div className="mt-1.5 flex items-baseline gap-1">
            <span className="font-display text-[28px] leading-none font-bold">{formatScore(overall)}</span>
            <span className="text-xs text-muted-foreground">/100</span>
          </div>
        </div>
      </div>
    </aside>
  )
}
