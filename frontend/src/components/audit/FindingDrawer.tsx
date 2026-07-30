import { useEffect, useRef, useState } from "react"
import { Check, Copy, ExternalLink, X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  buildIssueCardContent,
  COMPACT_SEVERITY_VARIANT,
  compactSeverityLabel,
  CURRENT_STATE_BY_TITLE,
  FIX_EXPLANATION_BY_TITLE,
  occurrenceElement,
  WCAG_REFERENCE_BY_TITLE,
} from "@/lib/issueText"
import type { Recommendation, Severity } from "@/types/audit"

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

/**
 * Right-side detail drawer for one Accessibility finding (or finding group).
 * Report list -> Open finding -> Review evidence -> Apply remediation: the
 * card only summarizes; everything else — evidence, occurrence-by-occurrence
 * element, the recommended fix (shown immediately, no separate "generate"
 * step), the WCAG reference (only when we actually have one) — lives here.
 *
 * Evidence deliberately has no fabricated "Affected HTML" block: the scraper
 * only ever captures button text/image src/field name, never outerHTML or
 * real CSS selectors, so showing invented markup would misrepresent what
 * AuditPilot actually inspected.
 */
export function FindingDrawer({
  title,
  severity,
  occurrences,
  pageUrl,
  reviewed,
  categoryLabel,
  onToggleReviewed,
  onClose,
}: {
  title: string
  severity: Severity
  occurrences: Recommendation[]
  pageUrl: string
  reviewed: boolean
  /** e.g. "Accessibility" or "SEO" — which category this finding came from. */
  categoryLabel: string
  onToggleReviewed: () => void
  onClose: () => void
}) {
  const [activeIndex, setActiveIndex] = useState(0)
  const [copiedFix, setCopiedFix] = useState(false)
  const [copiedSelector, setCopiedSelector] = useState(false)
  const [copiedSuggestion, setCopiedSuggestion] = useState(false)
  const [entered, setEntered] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  const active = occurrences[activeIndex] ?? occurrences[0]
  const { whyItMatters, recommendedFix } = buildIssueCardContent(title, active.description, pageUrl)
  const element = occurrenceElement(active)
  const wcagReference = WCAG_REFERENCE_BY_TITLE[title]
  const fixExplanation = FIX_EXPLANATION_BY_TITLE[title]
  const isGroup = occurrences.length > 1
  // Real, DOM-computed evidence — only shown when the scraper actually found
  // it, never invented. `element` (occurrenceElement) stays as the plain-
  // language fallback for checks that don't have a real CSS selector (e.g.
  // Missing Label's field name, Multiple H1's heading text).
  const location = active.section
  const selector = active.selector
  const aiSuggestion = active.ai_suggestion
  const currentState = CURRENT_STATE_BY_TITLE[title]

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement | null
    const raf = requestAnimationFrame(() => setEntered(true))
    panelRef.current?.focus()
    return () => {
      cancelAnimationFrame(raf)
      previousFocusRef.current?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose()
        return
      }
      if (event.key !== "Tab" || !panelRef.current) return

      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [onClose])

  async function handleCopyFix() {
    try {
      await navigator.clipboard.writeText(recommendedFix)
      setCopiedFix(true)
      setTimeout(() => setCopiedFix(false), 1800)
    } catch {
      // Clipboard can be blocked by browser permissions — the text is still
      // fully visible and selectable in the drawer.
    }
  }

  async function handleCopySuggestion() {
    if (!aiSuggestion) return
    try {
      await navigator.clipboard.writeText(aiSuggestion)
      setCopiedSuggestion(true)
      setTimeout(() => setCopiedSuggestion(false), 1800)
    } catch {
      // Clipboard can be blocked by browser permissions — the text is still
      // fully visible and selectable in the drawer.
    }
  }

  async function handleCopySelector() {
    const value = selector ?? element
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopiedSelector(true)
      setTimeout(() => setCopiedSelector(false), 1800)
    } catch {
      // Same as above — fail quietly.
    }
  }

  return (
    <div className="fixed inset-0 z-50 print:hidden" role="presentation">
      <div
        className={`absolute inset-0 bg-black/40 transition-opacity duration-300 motion-reduce:transition-none ${
          entered ? "opacity-100" : "opacity-0"
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${title} finding details`}
        tabIndex={-1}
        className={`absolute inset-y-0 right-0 flex h-full w-full flex-col overflow-y-auto bg-card shadow-2xl outline-none transition-transform duration-300 ease-out motion-reduce:transition-none sm:w-[90%] md:w-[75%] lg:w-[500px] ${
          entered ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b bg-card p-6">
          <div>
            <h2 className="font-display text-xl font-bold">{title}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
              <Badge variant={COMPACT_SEVERITY_VARIANT[severity]} className="font-semibold">
                {compactSeverityLabel(severity)}
              </Badge>
              <span>·</span>
              <span>{categoryLabel}</span>
              {isGroup && (
                <>
                  <span>·</span>
                  <span>{occurrences.length} occurrences</span>
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close finding details"
            className="flex size-9 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-6 p-6">
          <section>
            <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
              What happened
            </h3>
            <p className="mt-1.5 text-[15px] leading-relaxed text-foreground/80">{active.description}</p>
          </section>

          <section>
            <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
              Why it matters
            </h3>
            <p className="mt-1.5 text-[15px] leading-relaxed text-foreground/80">{whyItMatters}</p>
          </section>

          <section>
            <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">Evidence</h3>
            <div className="mt-2 flex flex-col gap-2.5 rounded-xl border bg-secondary/30 p-3.5 text-sm">
              <div>
                <div className="text-xs font-semibold text-muted-foreground">Page</div>
                <div className="mt-0.5 break-all">{pageUrl}</div>
              </div>
              {location && (
                <div>
                  <div className="text-xs font-semibold text-muted-foreground">Location</div>
                  <div className="mt-0.5">{location}</div>
                </div>
              )}
              {selector ? (
                <div>
                  <div className="text-xs font-semibold text-muted-foreground">Selector</div>
                  <div className="mt-0.5 font-mono text-[13px] break-all">{selector}</div>
                </div>
              ) : (
                element && (
                  <div>
                    <div className="text-xs font-semibold text-muted-foreground">Element</div>
                    <div className="mt-0.5 font-mono text-[13px] break-all">{element}</div>
                  </div>
                )
              )}
              {isGroup && (
                <div>
                  <div className="text-xs font-semibold text-muted-foreground">Occurrences</div>
                  <div className="mt-0.5">{occurrences.length} on this page</div>
                </div>
              )}
            </div>

            {isGroup && (
              <div className="mt-3">
                <div className="text-xs font-semibold text-muted-foreground">
                  Select an occurrence to view its evidence
                </div>
                <ul className="mt-1.5 flex flex-col gap-1">
                  {occurrences.map((occurrence, index) => {
                    const label = occurrenceElement(occurrence) ?? `Occurrence ${index + 1}`
                    return (
                      <li key={index}>
                        <button
                          type="button"
                          onClick={() => setActiveIndex(index)}
                          className={`flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                            index === activeIndex
                              ? "bg-primary/15 text-foreground"
                              : "text-muted-foreground hover:bg-secondary"
                          }`}
                        >
                          <span className="tabular-nums">{index + 1}.</span>
                          <span className="truncate font-mono">{label}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </section>

          <section>
            <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
              How to fix
            </h3>
            <p className="mt-1.5 text-[15px] leading-relaxed text-foreground/80">{recommendedFix}</p>
            {fixExplanation && (
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">{fixExplanation}</p>
            )}

            {aiSuggestion && (
              <div className="mt-3 rounded-xl border border-quickfix-bg bg-quickfix-bg/30 p-3.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold tracking-[0.08em] text-quickfix-text uppercase">
                    AI-suggested replacement · Gemini
                  </span>
                  <button
                    type="button"
                    onClick={handleCopySuggestion}
                    className="flex min-h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-xs font-semibold text-quickfix-text transition hover:bg-quickfix-bg/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    {copiedSuggestion ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    {copiedSuggestion ? "Copied" : "Copy"}
                  </button>
                </div>
                <div className="mt-2.5 flex flex-col gap-2 text-sm">
                  {currentState && (
                    <div>
                      <div className="text-xs font-semibold text-muted-foreground">Current</div>
                      <div className="mt-0.5 text-foreground/70">{currentState}</div>
                    </div>
                  )}
                  <div>
                    <div className="text-xs font-semibold text-muted-foreground">Suggested</div>
                    <div className="mt-0.5 font-medium text-foreground">"{aiSuggestion}"</div>
                  </div>
                </div>
                <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
                  Generated by Gemini from this page's real content — review before using; it's a
                  suggestion, not a verified fact.
                </p>
              </div>
            )}
          </section>

          {wcagReference && (
            <section>
              <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                Standard reference
              </h3>
              <p className="mt-1.5 text-[13px] font-medium text-foreground/80">{wcagReference}</p>
            </section>
          )}
        </div>

        <div className="sticky bottom-0 flex flex-col gap-2 border-t bg-card p-6 sm:flex-row">
          <button
            type="button"
            onClick={handleCopyFix}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {copiedFix ? <Check className="size-4" /> : <Copy className="size-4" />}
            {copiedFix ? "Copied" : "Copy fix"}
          </button>
          <button
            type="button"
            onClick={() => window.open(pageUrl, "_blank", "noopener,noreferrer")}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border px-4 text-sm font-semibold text-foreground/80 transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <ExternalLink className="size-4" />
            Open page
          </button>
          {(selector ?? element) && (
            <button
              type="button"
              onClick={handleCopySelector}
              className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full px-4 text-sm font-semibold text-muted-foreground transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-none"
            >
              {copiedSelector ? <Check className="size-4" /> : <Copy className="size-4" />}
              {copiedSelector ? "Copied" : "Copy selector"}
            </button>
          )}
          <button
            type="button"
            onClick={onToggleReviewed}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full px-4 text-sm font-semibold text-muted-foreground transition hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:flex-none"
          >
            <Check className="size-4" />
            {reviewed ? "Reviewed" : "Mark as reviewed"}
          </button>
        </div>
      </div>
    </div>
  )
}
