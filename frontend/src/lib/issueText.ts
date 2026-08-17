/**
 * Presentation-only helpers for turning raw backend text (Recommendation
 * descriptions, agent failure summaries) into something a founder, marketer,
 * or agency reading an audit report — not another engineer — can act on.
 *
 * Nothing here changes what the backend computed — it only reformats how we
 * *display* it: shortening long embedded URLs into readable labels,
 * translating a technical finding into a plain-language "why it matters" /
 * "recommended fix" pair, estimating how much effort a fix takes, and
 * merging the same underlying issue when multiple agents flag it.
 */

import type { AuditCategory, Recommendation, Severity } from "@/types/audit"

const URL_REGEX = /https?:\/\/[^\s'")<>]+/g

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}

// ---------------------------------------------------------------------------
// Plain-language "why it matters" + "recommended fix" content, keyed by the
// finite set of titles the backend can produce (Recommendation.title is
// always either a rule-based check name or a Copy/Visual dimension name —
// see backend/agents/*.py and backend/models/schemas.py). An unrecognized
// title (e.g. the backend adds a new check later) falls back to generic text
// rather than breaking.
// ---------------------------------------------------------------------------

const WHY_IT_MATTERS_BY_TITLE: Record<string, string> = {
  "Missing Alt Text":
    "Screen readers can't describe this image to visually impaired visitors, and search engines can't index it — a real accessibility barrier and a missed opportunity for search visibility.",
  "Missing Image Alt Text":
    "Search engines can't index this image, which is a missed opportunity for image-search traffic.",
  "Multiple H1":
    "Search engines and screen readers use your main heading to understand what the page is about — competing headings blur that signal.",
  "Empty Button":
    "Visitors using a screen reader or keyboard have no idea what this button does — a real barrier for part of your audience.",
  "Missing Label":
    "People using assistive technology can't tell what this form field is for, which can cause them to abandon your form.",
  "Missing Page Title":
    "The page title shows up in browser tabs, search results, and shared links — a missing one hurts usability and first impressions.",
  "Missing Title":
    "The page title is one of the first things people see in search results — a missing title makes your listing look unfinished and hurts click-through.",
  "Missing Meta Description":
    "This is the summary text shown under your link in search results. Without it, search engines write their own — usually less compelling.",
  "Missing H1":
    "Without a clear main heading, visitors and search engines both struggle to quickly understand what this page is about.",
  "Missing Open Graph Tags":
    "When this page is shared on social media, it'll show up without a proper preview image or title — links look broken or unappealing.",
  "Low Performance Score":
    "Slow-loading pages lose visitors before they see your content, and search engines factor speed into rankings.",
  "Slow Lcp":
    "Visitors perceive your site as slow if the main content takes too long to appear — a common reason people leave before converting.",
  "High Cls":
    "Content shifting around while the page loads is disorienting and can cause visitors to click the wrong thing.",
  "Slow Inp":
    "If the site feels sluggish to respond to clicks and taps, visitors assume something is broken.",
  "Value Proposition Clarity":
    "If visitors can't immediately tell what you offer and who it's for, most will leave without exploring further.",
  Readability:
    "Dense, hard-to-scan copy loses visitors' attention before they ever reach your call-to-action.",
  "Cta Quality":
    "Vague buttons like \"Submit\" or \"Click here\" convert worse than clear, specific calls-to-action.",
  Jargon:
    "Unexplained technical or internal terms confuse visitors who aren't already familiar with your product.",
  "Trust Signals":
    "Without credibility markers like testimonials, logos, or guarantees, visitors are more hesitant to convert.",
  "Visual Hierarchy":
    "If everything on the page competes for attention equally, visitors don't know where to look first.",
  "Cta Visibility":
    "A call-to-action that's easy to miss means fewer conversions, even if the offer itself is strong.",
  "Layout Issues":
    "Visual glitches make the site feel unpolished and can undermine visitor trust.",
  "Contrast Problems":
    "Low-contrast text is hard to read for many visitors and can exclude people with visual impairments.",
}

// ---------------------------------------------------------------------------
// Title normalization
//
// The backend now sends edited, human-readable titles ("CTA quality", not
// "Cta Quality"; "Button with no accessible name", not "Empty Button") so that
// every output — PDF, API, UI — reads the same way. The presentation maps here
// are keyed by the older machine-derived titles, and rekeying all of them would
// be churn for no gain, so lookups normalize through this table instead.
//
// Keyed lookups should prefer `Recommendation.rule_id` where a new call site
// can: rule ids are the stable contract, titles are editorial.
// ---------------------------------------------------------------------------

const LEGACY_TITLE_BY_LABEL: Record<string, string> = {
  "Missing alt text": "Missing Alt Text",
  "Missing image alt text": "Missing Image Alt Text",
  "Multiple H1 headings": "Multiple H1",
  "Button with no accessible name": "Empty Button",
  "Form field with no label": "Missing Label",
  "Missing page title": "Missing Page Title",
  "Missing meta description": "Missing Meta Description",
  "Missing H1 heading": "Missing H1",
  "Missing Open Graph tag": "Missing Open Graph Tags",
  "Low Lighthouse performance score": "Low Performance Score",
  "Slow LCP (Largest Contentful Paint)": "Slow Lcp",
  "High CLS (Cumulative Layout Shift)": "High Cls",
  "Slow INP (Interaction to Next Paint)": "Slow Inp",
  "Value proposition clarity": "Value Proposition Clarity",
  "Readability": "Readability",
  "CTA quality": "Cta Quality",
  "Jargon": "Jargon",
  "Trust signals": "Trust Signals",
  "Visual hierarchy": "Visual Hierarchy",
  "CTA visibility": "Cta Visibility",
  "Layout issues": "Layout Issues",
  "Contrast problems": "Contrast Problems",
}

/** Map a backend title onto the key the presentation maps in this file use. */
export function legacyTitleKey(title: string): string {
  return LEGACY_TITLE_BY_LABEL[title] ?? title
}

const GENERIC_WHY_IT_MATTERS =
  "Addressing this improves your site's overall quality and visitor experience."

export function getWhyItMatters(title: string): string {
  return WHY_IT_MATTERS_BY_TITLE[legacyTitleKey(title)] ?? GENERIC_WHY_IT_MATTERS
}

/**
 * Whether we have something real to say about this title.
 *
 * Lets a caller omit the line entirely rather than print the generic
 * fallback. Filler under a heading that promises "why it matters" is worse
 * than silence — it teaches the reader that these sentences carry no
 * information.
 */
export function hasWhyItMatters(title: string): boolean {
  return WHY_IT_MATTERS_BY_TITLE[legacyTitleKey(title)] !== undefined
}

/** Generic, factual remediation text for the finite set of rule-based check titles. */
const RECOMMENDED_FIX_BY_TITLE: Record<string, string> = {
  "Missing Alt Text": 'Add a descriptive alt attribute (or alt="" if the image is purely decorative).',
  "Missing Image Alt Text": 'Add a descriptive alt attribute (or alt="" if the image is purely decorative).',
  "Multiple H1": "Use a single <h1> per page and demote the rest to <h2> or lower.",
  "Empty Button": "Give the button visible text, a value, or an aria-label.",
  "Missing Label": "Associate the field with a <label> (via for/id, wrapping, or aria-label).",
  "Missing Page Title": "Add a descriptive <title> element to the page's <head>.",
  "Missing Title": "Add a descriptive <title> element to the page's <head>.",
  "Missing Meta Description": 'Add a <meta name="description"> summarizing the page in ~150-160 characters.',
  "Missing H1": "Add a single <h1> describing the page's main topic.",
  "Missing Open Graph Tags": "Add the missing Open Graph tag for clean social link previews.",
}

/**
 * The actual recommended fix to show. For rule-based checks (accessibility/
 * SEO) the backend's description is just a diagnostic sentence, so we swap
 * in curated fix text. For Performance/Copy/Visual, the backend's
 * description is already written as an actionable, page-specific fix (see
 * backend/agents/performance.py's _RECOMMENDATION_TEXT and the Gemini
 * prompts in agents/prompts/copy.py + visual.py) — so we keep it as-is.
 */
function getRecommendedFix(title: string, displayDescription: string): string {
  return RECOMMENDED_FIX_BY_TITLE[legacyTitleKey(title)] ?? displayDescription
}

// ---------------------------------------------------------------------------
// Effort estimation — a rough, static tier per title so a reader can tell
// "quick win" from "this needs a project" at a glance. Not a time-tracking
// system — just enough to help someone prioritize.
// ---------------------------------------------------------------------------

export type EffortTier = "quick" | "moderate" | "involved"

// "Quick win" (not "Quick fix") — reserves the word "fix" for the real
// Generate Fix action button, so the effort badge never reads like a
// second, competing action next to it.
export const EFFORT_LABEL: Record<EffortTier, string> = {
  quick: "Quick win",
  moderate: "Moderate effort",
  involved: "Involved",
}

const EFFORT_RANK: Record<EffortTier, number> = { quick: 0, moderate: 1, involved: 2 }

const EFFORT_BY_TITLE: Record<string, EffortTier> = {
  "Missing Alt Text": "quick",
  "Missing Image Alt Text": "quick",
  "Multiple H1": "quick",
  "Empty Button": "quick",
  "Missing Label": "quick",
  "Missing Page Title": "quick",
  "Missing Title": "quick",
  "Missing Meta Description": "quick",
  "Missing H1": "quick",
  "Missing Open Graph Tags": "quick",
  "Contrast Problems": "quick",
  "Low Performance Score": "involved",
  "Slow Lcp": "involved",
  "High Cls": "involved",
  "Slow Inp": "involved",
  "Value Proposition Clarity": "moderate",
  Readability: "moderate",
  "Cta Quality": "moderate",
  Jargon: "moderate",
  "Trust Signals": "moderate",
  "Visual Hierarchy": "moderate",
  "Cta Visibility": "moderate",
  "Layout Issues": "moderate",
}

export function effortFor(title: string): EffortTier {
  return EFFORT_BY_TITLE[legacyTitleKey(title)] ?? "moderate"
}

// ---------------------------------------------------------------------------
// URL shortening / affected-element extraction
// ---------------------------------------------------------------------------

/** Buckets a raw resource URL into a short, human-readable label. */
export function classifyResourceUrl(url: string, pageUrl?: string | null): string {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return "External resource"
  }

  const host = parsed.hostname.replace(/^www\./, "")
  const path = parsed.pathname.toLowerCase()
  const filename = path.split("/").filter(Boolean).pop() ?? ""
  const shortFile = filename.length > 22 ? `${filename.slice(0, 19)}…` : filename

  let pageHost: string | null = null
  try {
    pageHost = pageUrl ? new URL(pageUrl).hostname.replace(/^www\./, "") : null
  } catch {
    pageHost = null
  }

  if (/hero|banner|header/.test(path)) return `Hero image (${host})`
  if (/nav(?!igator)|logo|menu/.test(path)) return `Navigation image (${host})`
  if (pageHost && host !== pageHost) return `External image (${host})`
  return shortFile ? `Image (${host}/${shortFile})` : `Image (${host})`
}

export interface ParsedIssueText {
  /** Description with any long URLs replaced by a short label. Safe to render directly. */
  displayDescription: string
  /** Short label for the specific element this issue is about, if one could be found. */
  affectedElement: string | null
  /** Raw strings (full URLs) worth hiding behind a "Technical details" disclosure. */
  technicalDetails: string[]
}

/** Parses a Recommendation.description for display: shortens URLs, extracts an affected-element label. */
export function parseIssueDescription(description: string, pageUrl?: string | null): ParsedIssueText {
  const urls = description.match(URL_REGEX) ?? []

  if (urls.length === 0) {
    // No URL to shorten — fall back to any quoted identifier (e.g. a form field name).
    const quoted = description.match(/'([^']+)'/)
    return {
      displayDescription: description,
      affectedElement: quoted ? quoted[1] : null,
      technicalDetails: [],
    }
  }

  let display = description
  const labels: string[] = []
  for (const url of urls) {
    const label = classifyResourceUrl(url, pageUrl)
    labels.push(label)
    display = display.split(url).join(label)
  }

  return {
    displayDescription: display,
    affectedElement: labels[0] ?? null,
    technicalDetails: urls,
  }
}

/**
 * The real "affected element" evidence for one card, preferring the
 * backend's dedicated `context` field (a real image src, computed selector,
 * form field name, or heading text — see Recommendation.context) over the
 * older text-parsing heuristic, which only exists for checks/paths that
 * don't carry a structured context. A URL-shaped context gets the same
 * host/filename shortening used everywhere else, rather than printing a
 * long raw URL.
 */
export function resolveAffectedElement(
  context: string | null | undefined,
  fallbackDescription: string,
  pageUrl?: string | null
): string | null {
  const trimmed = context?.trim()
  if (trimmed) {
    return /^https?:\/\//i.test(trimmed) ? classifyResourceUrl(trimmed, pageUrl) : trimmed
  }
  return parseIssueDescription(fallbackDescription, pageUrl).affectedElement
}

/** Whether a resolved "affected element" reads better as a monospace code
 * block (a CSS selector, a raw metric like "2,450ms") than as a plain quote
 * (real page content — a heading, button label, filename, form field). */
export function looksLikeCode(value: string): boolean {
  const trimmed = value.trim()
  return /^[.#]/.test(trimmed) || / > /.test(trimmed) || /^-?[\d,]+(\.\d+)?\s?(ms|px|%|s)?$/i.test(trimmed)
}

/** Everything IssueItem needs to render one issue card, pre-computed from raw backend text. */
export interface IssueCardContent {
  whyItMatters: string
  recommendedFix: string
  affectedElement: string | null
  technicalDetails: string[]
  effort: EffortTier
}

export function buildIssueCardContent(
  title: string,
  description: string,
  pageUrl?: string | null,
  context?: string | null
): IssueCardContent {
  const { displayDescription, technicalDetails } = parseIssueDescription(description, pageUrl)
  return {
    whyItMatters: getWhyItMatters(title),
    recommendedFix: getRecommendedFix(title, displayDescription),
    affectedElement: resolveAffectedElement(context, description, pageUrl),
    technicalDetails,
    effort: effortFor(title),
  }
}

// ---------------------------------------------------------------------------
// Accessibility-only: WCAG references + fix explanations, keyed by the same
// finite set of titles AccessibilityAgent produces (see
// backend/agents/accessibility.py's AccessibilityCheck enum). Only shown for
// checks in this map — never invented for a title we don't recognize.
// ---------------------------------------------------------------------------

// Compact severity presentation for the new Accessibility findings list/drawer
// only — plain "Critical"/"High"/etc, not "<X> Severity" (the word "Severity"
// is redundant once it's clearly a status badge), and critical gets its own
// darker red so it reads as more serious than high, not identical to it.
// Scoped to this file/feature rather than the shared severityBadgeVariant map
// in lib/score.ts, which other categories still use unchanged.
export const COMPACT_SEVERITY_VARIANT: Record<
  Severity,
  "critical" | "destructive" | "warning" | "secondary" | "outline"
> = {
  critical: "critical",
  high: "destructive",
  medium: "warning",
  low: "secondary",
  info: "outline",
}

export function compactSeverityLabel(severity: Severity): string {
  return severity.charAt(0).toUpperCase() + severity.slice(1)
}

/** The real "current" state for the finite set of checks that can carry an
 * `ai_suggestion` — accurate precisely because each of these checks only
 * ever fires when the value is genuinely absent, so this is never a guess. */
export const CURRENT_STATE_BY_TITLE: Record<string, string> = {
  "Missing Title": "No <title> detected",
  "Missing Page Title": "No <title> detected",
  "Missing Alt Text": "No alt attribute detected",
  "Missing Image Alt Text": "No alt attribute detected",
}

export const WCAG_REFERENCE_BY_TITLE: Record<string, string> = {
  "Missing Alt Text": "WCAG 1.1.1 — Non-text Content",
  "Multiple H1": "WCAG 1.3.1 — Info and Relationships",
  "Empty Button": "WCAG 4.1.2 — Name, Role, Value",
  "Missing Label": "WCAG 3.3.2 — Labels or Instructions",
  "Missing Page Title": "WCAG 2.4.2 — Page Titled",
}

/** Short, genuine explanation of *why* the recommended fix resolves the issue
 * (distinct from "why it matters", which is about user impact). */
export const FIX_EXPLANATION_BY_TITLE: Record<string, string> = {
  "Missing Alt Text":
    "Alt text gives assistive technology a text alternative to announce, so the image's purpose is no longer invisible to screen reader users.",
  "Multiple H1":
    "A single, unique <h1> gives assistive technology and search engines one clear entry point for the page's main topic instead of several competing signals.",
  "Empty Button":
    "An aria-label or visible text gives the button a name assistive technology can announce, so its purpose is no longer a mystery to screen reader and keyboard users.",
  "Missing Label":
    "Associating the field with a label gives assistive technology a name to announce when the field receives focus.",
  "Missing Page Title":
    "A descriptive title gives browser tabs, search results, and screen readers something meaningful to announce for the page.",
}

/** The real distinguishing evidence for one occurrence — prefers the backend's
 * dedicated `context` field, falling back to the older text-parsing heuristic
 * for checks that embed it in the message instead (e.g. SEO's image src).
 * When the context is itself a full image URL, it's shortened to a readable
 * host/filename label (the same treatment already used elsewhere) instead of
 * printing the raw, often very long, URL. Non-URL context (a button locator
 * like "#add-to-cart", a form field name, actual <h1> text) is real and
 * already short, so it's shown as-is. */
export function occurrenceElement(item: Recommendation): string | null {
  return resolveAffectedElement(item.context, item.description)
}

export interface FindingGroup {
  title: string
  /** Highest severity among this group's occurrences. */
  severity: Severity
  occurrences: Recommendation[]
}

/**
 * Groups Recommendations by title — the same rule (e.g. "Empty Button" or
 * SEO's "Missing Alt Text") firing on multiple elements becomes one group
 * with N occurrences, instead of N visually-identical cards. A title with
 * exactly one occurrence is still a "group" of size 1; callers render those
 * as a plain single card. Used by both the Accessibility and SEO findings
 * sections (see GroupedFindingsSection) — Performance's findings are each a
 * distinct metric title already, so it doesn't need this.
 */
export function groupFindingsByTitle(items: Recommendation[]): FindingGroup[] {
  const groups = new Map<string, Recommendation[]>()
  for (const item of items) {
    const list = groups.get(item.title)
    if (list) list.push(item)
    else groups.set(item.title, [item])
  }

  const result: FindingGroup[] = []
  for (const [title, list] of groups.entries()) {
    const sorted = [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
    result.push({ title, severity: sorted[0].severity, occurrences: list })
  }

  result.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
  return result
}

// ---------------------------------------------------------------------------
// Cross-category deduplication — the same underlying problem is often
// flagged by more than one agent (e.g. "Multiple H1" from both Accessibility
// and SEO, or the same image missing alt text flagged by both). Rather than
// showing it twice, merge into one card and list every category it affects.
// ---------------------------------------------------------------------------

export interface DedupedIssue {
  title: string
  description: string
  severity: Severity
  categories: AuditCategory[]
  /** Real distinguishing evidence carried over from the primary (highest-
   * severity) merged Recommendation — same field, same meaning as
   * Recommendation.context/selector/section. */
  context?: string | null
  selector?: string | null
  section?: string | null
}

function firstUrl(description: string): string | null {
  const match = description.match(URL_REGEX)
  return match ? match[0].toLowerCase() : null
}

/**
 * Merges Recommendations that are almost certainly the same underlying
 * issue: same embedded resource URL (e.g. the same image flagged by two
 * different agents), or — if there's no URL — the same title (e.g.
 * "Multiple H1" flagged by both Accessibility and SEO). The merged entry
 * keeps the highest-severity title/description and lists every category
 * that flagged it.
 */
export function dedupeRecommendations(items: Recommendation[]): DedupedIssue[] {
  const groups = new Map<string, Recommendation[]>()

  for (const item of items) {
    const url = firstUrl(item.description)
    const key = url ? `url:${url}` : `title:${item.title.toLowerCase().trim()}`
    const list = groups.get(key)
    if (list) {
      list.push(item)
    } else {
      groups.set(key, [item])
    }
  }

  const merged: DedupedIssue[] = []
  for (const list of groups.values()) {
    const sorted = [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
    const primary = sorted[0]
    const categories = Array.from(new Set(list.map((item) => item.category)))
    merged.push({
      title: primary.title,
      description: primary.description,
      severity: primary.severity,
      categories,
      context: primary.context,
      selector: primary.selector,
      section: primary.section,
    })
  }

  merged.sort((a, b) => {
    const bySeverity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]
    if (bySeverity !== 0) return bySeverity
    return EFFORT_RANK[effortFor(a.title)] - EFFORT_RANK[effortFor(b.title)]
  })

  return merged
}

// ---------------------------------------------------------------------------
// Unavailable-category explanations (Performance/Copy/Visual can fail
// independently without taking down the rest of the audit — see
// backend/orchestrator.py's run_agent_safely).
// ---------------------------------------------------------------------------

const UNAVAILABLE_EXPLANATIONS: Partial<Record<AuditCategory, string>> = {
  accessibility: "We couldn't complete the accessibility checks for this page.",
  seo: "We couldn't complete the SEO checks for this page.",
  performance:
    "We couldn't run a Lighthouse performance audit for this page. This is usually temporary — try running the audit again in a few minutes.",
  copy: "We couldn't reach Gemini to review this page's messaging. This can happen when the AI service is temporarily rate-limited or unreachable — try again shortly.",
  visual:
    "We couldn't capture or analyze a screenshot of this page. This can happen when the AI service is temporarily rate-limited, or the page couldn't be rendered — try again shortly.",
}

export interface UnavailableExplanation {
  explanation: string
  technicalDetail: string | null
}

/** Turns a CategoryResult with score=null into a friendly explanation + optional raw technical detail. */
export function describeUnavailable(
  category: AuditCategory,
  summary: string | null
): UnavailableExplanation {
  const explanation = UNAVAILABLE_EXPLANATIONS[category] ?? "This analysis isn't available for this audit."
  if (!summary) {
    return { explanation, technicalDetail: null }
  }
  const technicalDetail = summary.startsWith("Analysis failed:")
    ? summary.slice("Analysis failed:".length).trim()
    : summary
  return { explanation, technicalDetail }
}
