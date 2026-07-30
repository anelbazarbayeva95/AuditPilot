import { Check, ChevronRight } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  COMPACT_SEVERITY_VARIANT,
  compactSeverityLabel,
  getWhyItMatters,
  looksLikeCode,
  occurrenceElement,
} from "@/lib/issueText"
import { isElevatedSeverity, severityStripeClass } from "@/lib/score"
import { cn } from "@/lib/utils"
import type { Recommendation, Severity } from "@/types/audit"

const MAX_OCCURRENCE_CHIPS = 3

/**
 * One scannable row in the Accessibility/SEO findings list, evidence-first:
 * the real detected element (a heading, a button locator, an image
 * filename) is shown prominently near the top — either as one large
 * "Detected" block for a single occurrence, or as a handful of real chips
 * for a group — so the report can be recognized by page element rather than
 * read as a paragraph. The explanatory sentence is still here, just
 * secondary. One low-emphasis "View details" action; no Inspect Issue/
 * Generate Fix buttons — those live inside the drawer, opened by clicking
 * anywhere on the card.
 */
export function FindingCard({
  id,
  title,
  severity,
  occurrences,
  reviewed,
  onOpen,
}: {
  id?: string
  title: string
  severity: Severity
  occurrences: Recommendation[]
  /** Client-side-only workflow marker set via the drawer's "Mark as reviewed" action. */
  reviewed?: boolean
  onOpen: () => void
}) {
  const isGroup = occurrences.length > 1
  const primary = occurrences[0]
  const element = !isGroup ? occurrenceElement(primary) : null
  // Only meaningful for a single occurrence — a group can span several
  // sections (e.g. buttons in both the header and footer), so it's left for
  // the drawer's per-occurrence evidence instead of guessed at here.
  const location = !isGroup ? primary.section : null

  // For a group, show a handful of the *real* distinct occurrence values as
  // chips instead of just a count — lets a reader recognize which elements
  // are affected without opening the drawer.
  const occurrenceChips = isGroup
    ? Array.from(new Set(occurrences.map(occurrenceElement).filter((value): value is string => !!value)))
    : []
  const visibleChips = occurrenceChips.slice(0, MAX_OCCURRENCE_CHIPS)
  const hiddenChipCount = occurrenceChips.length - visibleChips.length

  return (
    <li
      id={id}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onOpen()
        }
      }}
      className={cn(
        "relative scroll-mt-24 flex cursor-pointer flex-col gap-1.5 overflow-hidden rounded-[14px] border p-4 pl-5 break-inside-avoid",
        "transition-[transform,box-shadow,background-color] duration-150 ease-out",
        "hover:-translate-y-0.5 hover:bg-secondary/40 hover:shadow-[0_10px_24px_-18px_rgba(20,22,28,0.4)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "print:cursor-auto print:hover:translate-y-0 print:hover:shadow-none",
        isElevatedSeverity(severity) && "bg-destructive/[0.03]"
      )}
    >
      <div className={cn("absolute inset-y-0 left-0 w-[4px]", severityStripeClass[severity])} />
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-1.5 font-display text-[15px] font-bold">
          {title}
          {reviewed && (
            <span
              title="Marked as reviewed"
              className="flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-[11px] font-semibold text-success"
            >
              <Check className="size-3" />
              Reviewed
            </span>
          )}
        </span>
        <Badge variant={COMPACT_SEVERITY_VARIANT[severity]} className="shrink-0 font-semibold">
          {compactSeverityLabel(severity)}
        </Badge>
      </div>

      {!isGroup && element && (
        <div className="rounded-xl border bg-secondary/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
              Detected
            </span>
            {location && <span className="text-[11px] font-medium text-muted-foreground">{location}</span>}
          </div>
          {looksLikeCode(element) ? (
            <div className="mt-1 rounded-lg bg-muted px-2.5 py-1.5 font-mono text-[13px] break-all text-foreground">
              {element}
            </div>
          ) : (
            <div className="mt-1 font-display text-base leading-snug font-bold break-words text-foreground">
              “{element}”
            </div>
          )}
        </div>
      )}

      {isGroup && (
        <div>
          <div className="text-xs font-semibold text-muted-foreground">
            {occurrences.length} occurrences on this page
          </div>
          {visibleChips.length > 0 && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {visibleChips.map((chip, index) => (
                <span
                  key={index}
                  className={cn(
                    "inline-flex max-w-[220px] items-center rounded-md border bg-card px-2 py-1 text-xs break-words text-foreground/80",
                    looksLikeCode(chip) && "font-mono"
                  )}
                >
                  {chip}
                </span>
              ))}
              {hiddenChipCount > 0 && (
                <span className="text-xs font-medium text-muted-foreground">+{hiddenChipCount} more</span>
              )}
            </div>
          )}
        </div>
      )}

      <p className="text-xs text-foreground/60">{getWhyItMatters(title)}</p>

      <span className="mt-0.5 flex w-fit items-center gap-1 text-xs font-semibold text-link">
        {isGroup ? "View occurrences" : "View details"}
        <ChevronRight className="size-3.5" />
      </span>
    </li>
  )
}
