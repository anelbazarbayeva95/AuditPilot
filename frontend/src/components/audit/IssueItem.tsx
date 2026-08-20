import { useState } from "react"
import { Eye, Wand2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { IssueDetailModal } from "@/components/audit/IssueDetailModal"
import { isElevatedSeverity, severityBadgeVariant, severityLabel, severityStripeClass } from "@/lib/score"
import {
  buildIssueCardContent,
  EFFORT_LABEL,
  type EffortTier,
  getWhyItMatters,
  hasWhyItMatters,
  looksLikeCode,
} from "@/lib/issueText"
import { cn } from "@/lib/utils"
import type { EffortLevel, Severity, TimingBand } from "@/types/audit"

/** When this work should be scheduled — derived by the backend from impact, effort and confidence. */
const TIMING_LABEL: Record<TimingBand, string> = {
  immediate: "Immediate",
  next_sprint: "Next sprint",
  backlog: "Backlog",
}

/**
 * A single issue card, evidence-first: the real detected element/value (a
 * heading, a button label, an image filename, a raw metric like "2,450ms")
 * is the first thing a reader sees, in a visually distinct block, so the
 * report can be skimmed by recognized page elements rather than read
 * paragraph by paragraph. The why-it-matters/recommended-fix explanation is
 * still here, just secondary — smaller, muted, below the evidence.
 *
 * The card stays compact; two explicit, equally-sized actions both open
 * IssueDetailModal with the full why/fix text, affected element, and
 * technical details — "Inspect Issue" opens it at the top, "Generate Fix"
 * opens it scrolled straight to the Recommended Fix section. Same real data
 * either way, just a different entry point depending on what the user
 * already knows they want. Severity/effort are plain status badges, never
 * styled to look like a third action.
 */
export function IssueItem({
  id,
  title,
  description,
  severity,
  categoryLabels,
  ordinal,
  pageUrl,
  context,
  section,
  findingsResolved,
  standard,
  estimatedSaving,
  timing,
  effort: effortOverride,
  owner,
  authored,
  className,
}: {
  /** DOM id — lets the Results page's "in this section" rail jump straight to this card. */
  id?: string
  title: string
  description: string
  severity: Severity
  /** Badges for every category this issue affects. Omit inside a single-category
   * card (e.g. the Accessibility card) where it would just be redundant. */
  categoryLabels?: string[]
  /** Position in a priority-ordered list (1, 2, 3, ...) — shown as a leading badge. */
  ordinal?: number
  pageUrl?: string | null
  /** Real distinguishing evidence (image src, computed selector, form field
   * name, heading text, a raw metric) — see Recommendation.context. */
  context?: string | null
  /** Nearest real landmark ("Header", "Navigation", "Footer", "Main content"), if known. */
  section?: string | null
  /** How many findings this one fix closes — >1 when it spans categories. */
  findingsResolved?: number
  /** The standard this fix satisfies, e.g. a WCAG criterion, supplied by the backend. */
  standard?: string | null
  /** Measured saving for performance work — never estimated in the UI. */
  estimatedSaving?: string | null
  timing?: TimingBand | null
  /** Backend-supplied effort. Overrides the local heuristic when present. */
  effort?: EffortLevel | null
  /** Only ever set from caller-supplied config; renders as "Unassigned" otherwise. */
  owner?: string | null
  /** True when `description` is backend-authored, page-specific text that
   *  should be shown verbatim rather than passed through local heuristics. */
  authored?: boolean
  className?: string
}) {
  const [modalFocus, setModalFocus] = useState<"top" | "fix" | null>(null)
  const derived = buildIssueCardContent(title, description, pageUrl, context)

  // Backend-authored text is already specific to this page — it names the real
  // files and their measured cost. Running it back through the local
  // heuristics actively damages it: the URL classifier reads main.css out of a
  // render-blocking recommendation and captions it "Image (nike.com/main.css)",
  // which is invented evidence of exactly the kind the rest of the product
  // refuses to produce. So authored actions render their own text verbatim,
  // with no derived element and no generic why-it-matters filler.
  const whyItMatters = authored
    ? hasWhyItMatters(title)
      ? getWhyItMatters(title)
      : null
    : derived.whyItMatters
  const recommendedFix = authored ? description : derived.recommendedFix
  const affectedElement = authored ? null : derived.affectedElement
  const technicalDetails = authored ? [] : derived.technicalDetails
  const derivedEffort = derived.effort
  // Prefer the backend's effort: it's the same value the PDF prints, so the
  // two documents can't quote different numbers for the same work.
  const effort: EffortTier =
    effortOverride === "quick" || effortOverride === "moderate" || effortOverride === "involved"
      ? effortOverride
      : derivedEffort
  const metadata = [
    findingsResolved && findingsResolved > 1 ? `Closes ${findingsResolved} findings` : null,
    estimatedSaving ? `Saves ${estimatedSaving}` : null,
    timing ? TIMING_LABEL[timing] : null,
    standard,
    owner ? `Owner: ${owner}` : null,
  ].filter((value): value is string => !!value)

  return (
    <>
      <li
        id={id}
        className={cn(
          "relative scroll-mt-24 flex flex-col gap-3 overflow-hidden rounded-[15px] border p-4 pl-5 break-inside-avoid",
          isElevatedSeverity(severity) && "bg-severity-high-bg/40",
          className
        )}
      >
        <div className={cn("absolute inset-y-0 left-0 w-[4px]", severityStripeClass[severity])} />
        <div className="flex flex-wrap items-start justify-between gap-2">
          <span className="flex items-center gap-2.5 font-display text-[15px] font-bold">
            {ordinal !== undefined && (
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary font-display text-xs font-bold text-primary-foreground">
                {ordinal}
              </span>
            )}
            {title}
          </span>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            <Badge variant="outline" className="font-normal text-muted-foreground">
              {EFFORT_LABEL[effort]}
            </Badge>
            <Badge variant={severityBadgeVariant[severity]}>{severityLabel(severity)}</Badge>
          </div>
        </div>

        {categoryLabels && categoryLabels.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Affects:</span>
            {categoryLabels.map((label) => (
              <Badge key={label} variant="secondary" className="font-semibold">
                {label}
              </Badge>
            ))}
          </div>
        )}

        {affectedElement && (
          <div className="rounded-xl border bg-secondary/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                Detected
              </span>
              {section && <span className="text-[11px] font-medium text-muted-foreground">{section}</span>}
            </div>
            {looksLikeCode(affectedElement) ? (
              <div className="mt-1 rounded-lg bg-muted px-2.5 py-1.5 font-mono text-[13px] break-all text-foreground">
                {affectedElement}
              </div>
            ) : (
              <div className="mt-1 font-display text-base leading-snug font-bold break-words text-foreground">
                “{affectedElement}”
              </div>
            )}
          </div>
        )}

        <div className="line-clamp-3 print:line-clamp-none">
          {whyItMatters && (
            <p className="text-[13px] leading-relaxed text-foreground/70">
              <span className="font-semibold text-foreground/85">Why it matters: </span>
              {whyItMatters}
            </p>
          )}
          <p className="text-[13px] leading-relaxed text-foreground/70">
            <span className="font-semibold text-foreground/85">Recommended fix: </span>
            {recommendedFix}
          </p>
        </div>

        {metadata.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
            {metadata.map((entry, index) => (
              <span key={index} className="flex items-center gap-2.5">
                {index > 0 && <span aria-hidden="true">·</span>}
                {entry}
              </span>
            ))}
          </div>
        )}

        <div className="mt-1 flex flex-col gap-2 print:hidden sm:flex-row">
          <button
            type="button"
            onClick={() => setModalFocus("top")}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border px-4 text-sm font-semibold text-foreground/80 transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-none"
          >
            <Eye className="size-4" />
            Inspect Issue
          </button>
          <button
            type="button"
            onClick={() => setModalFocus("fix")}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-none"
          >
            <Wand2 className="size-4" />
            Generate Fix
          </button>
        </div>
      </li>

      {modalFocus && (
        <IssueDetailModal
          title={title}
          severity={severity}
          effort={effort}
          categoryLabels={categoryLabels}
          whyItMatters={whyItMatters ?? getWhyItMatters(title)}
          recommendedFix={recommendedFix}
          affectedElement={affectedElement}
          location={section}
          technicalDetails={technicalDetails}
          focusSection={modalFocus}
          onClose={() => setModalFocus(null)}
        />
      )}
    </>
  )
}
