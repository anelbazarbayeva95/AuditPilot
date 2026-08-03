import { useState } from "react"
import { Eye } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { IssueDetailModal } from "@/components/audit/IssueDetailModal"
import { isElevatedSeverity, severityBadgeVariant, severityLabel, severityStripeClass } from "@/lib/score"
import { buildIssueCardContent, EFFORT_LABEL, looksLikeCode } from "@/lib/issueText"
import { cn } from "@/lib/utils"
import type { Severity } from "@/types/audit"

/**
 * A single issue card, evidence-first: the real detected element/value (a
 * heading, a button label, an image filename, a raw metric like "2,450ms")
 * is the first thing a reader sees, in a visually distinct block, so the
 * report can be skimmed by recognized page elements rather than read
 * paragraph by paragraph. The why-it-matters/recommended-fix explanation is
 * still here, just secondary — smaller, muted, below the evidence.
 *
 * The card stays compact; one "Inspect Issue" action opens IssueDetailModal
 * with the full why/fix text, affected element, and technical details — the
 * report stays evidence-first rather than framed as something to trigger an
 * action on. Severity/effort are plain status badges, never styled to look
 * like a second action next to it.
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
  className?: string
}) {
  const [modalOpen, setModalOpen] = useState(false)
  const { whyItMatters, recommendedFix, affectedElement, technicalDetails, effort } = buildIssueCardContent(
    title,
    description,
    pageUrl,
    context
  )

  return (
    <>
      <li
        id={id}
        className={cn(
          "relative scroll-mt-24 flex flex-col gap-3 overflow-hidden rounded-[15px] border p-4 pl-5 break-inside-avoid",
          isElevatedSeverity(severity) && "bg-destructive/[0.03]",
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

        <div className="line-clamp-2 print:line-clamp-none">
          <p className="text-xs text-foreground/60">
            <span className="font-semibold text-foreground/80">Why it matters: </span>
            {whyItMatters}
          </p>
          <p className="text-xs text-foreground/60">
            <span className="font-semibold text-foreground/80">Recommended fix: </span>
            {recommendedFix}
          </p>
        </div>

        <div className="mt-1 print:hidden">
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-full border px-4 text-sm font-semibold text-foreground/80 transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Eye className="size-4" />
            Inspect Issue
          </button>
        </div>
      </li>

      {modalOpen && (
        <IssueDetailModal
          title={title}
          severity={severity}
          effort={effort}
          categoryLabels={categoryLabels}
          whyItMatters={whyItMatters}
          recommendedFix={recommendedFix}
          affectedElement={affectedElement}
          location={section}
          technicalDetails={technicalDetails}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  )
}
