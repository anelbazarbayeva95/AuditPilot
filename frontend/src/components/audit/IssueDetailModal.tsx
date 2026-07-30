import { useEffect, useRef, useState } from "react"
import { Check, Copy, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { EFFORT_LABEL, looksLikeCode, type EffortTier } from "@/lib/issueText"
import { severityBadgeVariant, severityLabel } from "@/lib/score"
import type { Severity } from "@/types/audit"

/**
 * Expanded detail view for a single issue — same content model as the
 * compact IssueItem card (why it matters / recommended fix / severity /
 * effort / affected element / technical details), just given full real
 * estate instead of a line-clamped card + tiny "Show more" toggle and a
 * barely-visible <details> disclosure. No new data: everything shown here
 * is the same buildIssueCardContent() output IssueItem already computes.
 *
 * Opened from one of two entry points on the card (see IssueItem.tsx):
 * "Inspect Issue" opens at the top; "Generate Fix" opens scrolled straight
 * to the Recommended Fix section via `focusSection="fix"`. Both show the
 * same real, already-computed data — there's no separate AI call here.
 */
export function IssueDetailModal({
  title,
  severity,
  effort,
  categoryLabels,
  whyItMatters,
  recommendedFix,
  affectedElement,
  location,
  technicalDetails,
  focusSection = "top",
  onClose,
}: {
  title: string
  severity: Severity
  effort: EffortTier
  categoryLabels?: string[]
  whyItMatters: string
  recommendedFix: string
  affectedElement: string | null
  /** Nearest real landmark ("Header", "Navigation", "Footer", "Main content"), if known. */
  location?: string | null
  technicalDetails: string[]
  /** Which part of the modal to scroll to right after it opens. */
  focusSection?: "top" | "fix"
  onClose: () => void
}) {
  const fixSectionRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [onClose])

  useEffect(() => {
    if (focusSection === "fix") {
      fixSectionRef.current?.scrollIntoView({ block: "start" })
    }
  }, [focusSection])

  async function handleCopyRecommendation() {
    try {
      await navigator.clipboard.writeText(recommendedFix)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard access can be blocked by browser permissions — fail quietly,
      // the text is still fully visible/selectable on the page.
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 print:hidden"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-[20px] bg-card p-7 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className="font-normal text-muted-foreground">
              {EFFORT_LABEL[effort]}
            </Badge>
            <Badge variant={severityBadgeVariant[severity]}>{severityLabel(severity)}</Badge>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        <h2 className="mt-3 font-display text-xl font-bold">{title}</h2>

        {categoryLabels && categoryLabels.length > 0 && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Affects:</span>
            {categoryLabels.map((label) => (
              <Badge key={label} variant="secondary" className="font-semibold">
                {label}
              </Badge>
            ))}
          </div>
        )}

        <div className="mt-5 flex flex-col gap-4">
          {affectedElement && (
            <div className="rounded-xl border bg-secondary/40 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                  Detected
                </span>
                {location && <span className="text-[11px] font-medium text-muted-foreground">{location}</span>}
              </div>
              {looksLikeCode(affectedElement) ? (
                <div className="mt-1.5 rounded-lg bg-muted px-2.5 py-1.5 font-mono text-sm break-all text-foreground">
                  {affectedElement}
                </div>
              ) : (
                <div className="mt-1.5 font-display text-lg leading-snug font-bold break-words text-foreground">
                  “{affectedElement}”
                </div>
              )}
            </div>
          )}

          <div>
            <div className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
              Why it matters
            </div>
            <p className="mt-1.5 text-[15px] leading-relaxed text-foreground/80">{whyItMatters}</p>
          </div>
          <div ref={fixSectionRef} className="scroll-mt-4 rounded-xl bg-quickfix-bg/40 p-3.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                Recommended fix
              </div>
              <button
                type="button"
                onClick={handleCopyRecommendation}
                className="flex min-h-8 items-center gap-1.5 rounded-full border bg-card px-3 text-xs font-semibold text-foreground/80 transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
                {copied ? "Copied" : "Copy Recommendation"}
              </button>
            </div>
            <p className="mt-1.5 text-[15px] leading-relaxed text-foreground/80">{recommendedFix}</p>
          </div>

          {technicalDetails.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                Technical details
              </div>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {technicalDetails.map((url, index) => (
                  <li key={index} className="rounded-lg bg-muted p-2 font-mono text-xs break-all text-muted-foreground">
                    {url}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
