import { type FormEvent, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  AlertCircle,
  ArrowRight,
  Check,
  FileText,
  Gauge,
  Globe,
  Loader2,
  MessageSquare,
  Search,
  SlidersHorizontal,
  Sparkles,
  Zap,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ApiError, createReportJob } from "@/lib/api"
import { getScoreBand, scoreBandIndicatorClass } from "@/lib/score"

/** Normalizes user input into a fully-qualified URL, or returns null if invalid. */
function normalizeUrl(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed) return null

  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`

  try {
    const parsed = new URL(candidate)
    if (!parsed.hostname.includes(".")) return null
    return parsed.toString()
  } catch {
    return null
  }
}

const DEMO_URL = "https://yourwebsite.com/"

// airbnb.com was swapped out — its homepage's below-the-fold content loads
// well after the "load" event, which produced a blank/misleading screenshot
// capture (see backend/screenshot.py, which waits on "load" only).
const TRY_DOMAINS = ["nike.com", "amazon.com", "stripe.com"]

const TRUST_BULLETS = ["Average audit: 35s", "5 AI agents", "Lighthouse + Gemini", "No signup required"]

const PROCESS_STEPS = [
  {
    icon: Zap,
    tool: "Playwright",
    title: "Scrape",
    description: "Capture screenshots, metadata, and the full DOM from the live page.",
  },
  {
    icon: Search,
    tool: "Lighthouse",
    title: "Analyze",
    description: "Lighthouse audits performance; rule-based checks cover accessibility and SEO.",
  },
  {
    icon: Sparkles,
    tool: "Gemini",
    title: "AI Review",
    description: "Reviews messaging quality, copy clarity, and visual design.",
  },
  {
    icon: MessageSquare,
    tool: "AuditPilot",
    title: "Report",
    description: "A prioritized, ready-to-action list — not just raw findings.",
    inverted: true,
  },
]

const MOCK_CATEGORY_SCORES: { label: string; score: number }[] = [
  { label: "Accessibility", score: 92 },
  { label: "SEO", score: 84 },
  { label: "Performance", score: 79 },
  { label: "Copy", score: 88 },
  { label: "Visual", score: 91 },
]

const MOCK_OVERALL_START = 58
const MOCK_OVERALL_TARGET = 87

const CRITICAL_FINDINGS = [
  "24 images missing alt text",
  "Largest Contentful Paint: 4.8s",
  "Missing meta description",
  "CTA button contrast fails WCAG AA",
]

const PREVIEW_STATS = [
  { value: "9", label: "Critical issues" },
  { value: "7", label: "Warnings" },
  { value: "~35m", label: "Est. fix time", accent: true },
  { value: "+16pts", label: "Possible SEO gain", accent: true },
]

const POWERED_BY = ["Playwright", "Lighthouse", "Gemini", "WCAG 2.1"]

/** Fires once the wrapped element scrolls into view, then stops observing. */
function useInView<T extends HTMLElement>(threshold = 0.25) {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true)
          observer.disconnect()
        }
      },
      { threshold }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold])

  return [ref, inView] as const
}

/** Eases from `start` to `target` over `durationMs` once `active` flips true. */
function useCountUp(target: number, start: number, active: boolean, durationMs = 1400) {
  const [value, setValue] = useState(start)

  useEffect(() => {
    if (!active) return
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const progress = Math.min(1, (t - t0) / durationMs)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(start + (target - start) * eased))
      if (progress < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, target, start, durationMs])

  return value
}

/** Loops a type-then-delete effect over `fullText` — used only as an animated
 *  placeholder overlay, never as the real input value. */
function useTypewriter(fullText: string, active: boolean) {
  const [chars, setChars] = useState(0)

  useEffect(() => {
    if (!active) return
    let dir: 1 | 0 | -1 = 1
    let pauseTimeout: ReturnType<typeof setTimeout> | undefined

    const interval = setInterval(() => {
      setChars((c) => {
        if (dir === 1) {
          if (c < fullText.length) return c + 1
          dir = 0
          pauseTimeout = setTimeout(() => {
            dir = -1
          }, 10000)
          return c
        }
        if (dir === -1) {
          if (c > 0) return c - 1
          dir = 1
          return c
        }
        return c
      })
    }, 130)

    return () => {
      clearInterval(interval)
      if (pauseTimeout) clearTimeout(pauseTimeout)
    }
  }, [fullText, active])

  return fullText.slice(0, chars)
}

export function UrlInputPage() {
  const navigate = useNavigate()
  const [url, setUrl] = useState("")
  const [isFocused, setIsFocused] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const [previewRef, previewInView] = useInView<HTMLDivElement>()
  const overallScore = useCountUp(MOCK_OVERALL_TARGET, MOCK_OVERALL_START, previewInView)

  const typedUrl = useTypewriter(DEMO_URL, true)
  const showTypedOverlay = !isFocused && url.length === 0

  const heroInputRef = useRef<HTMLInputElement>(null)
  const heroSectionRef = useRef<HTMLDivElement>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setApiError(null)

    const normalized = normalizeUrl(url)
    if (!normalized) {
      setValidationError("Enter a valid website URL, e.g. example.com")
      return
    }
    setValidationError(null)
    setIsLoading(true)

    try {
      const jobId = await createReportJob(normalized)
      navigate("/progress", { state: { jobId, url: normalized } })
    } catch (err) {
      setApiError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong starting this audit. Please try again."
      )
      setIsLoading(false)
    }
  }

  function fillTryDomain(domain: string) {
    setUrl(domain)
    setValidationError(null)
    heroInputRef.current?.focus()
  }

  function focusHero() {
    heroSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
    heroInputRef.current?.focus()
  }

  return (
    <main
      className="flex flex-col"
      style={{ background: "linear-gradient(180deg, #FAFAF9 0%, #F6F6F5 340px, #FFFFFF 720px)" }}
    >
      {/* Header */}
      <header className="mx-auto flex w-full max-w-[1180px] items-center justify-between px-6 pt-7 sm:px-8">
        <div className="flex items-center gap-2.5">
          <div className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-primary">
            <Zap className="size-[17px] text-primary-foreground" />
          </div>
          <div>
            <div className="font-display text-[17px] leading-none font-bold tracking-tight">AuditPilot</div>
            <div className="mt-[3px] text-[10px] font-semibold tracking-[0.1em] text-muted-foreground uppercase">
              AI Website Intelligence
            </div>
          </div>
        </div>
        <nav className="hidden items-center gap-7 sm:flex">
          <a href="#how-it-works" className="text-[13px] font-medium text-foreground/70 hover:text-foreground">
            Features
          </a>
          <a href="#preview" className="text-[13px] font-medium text-foreground/70 hover:text-foreground">
            Demo
          </a>
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground/50">
            Pricing
            <span className="rounded-full bg-secondary px-[7px] py-[2px] text-[9px] font-semibold tracking-wide text-muted-foreground uppercase">
              Soon
            </span>
          </span>
        </nav>
      </header>

      {/* Hero */}
      <section ref={heroSectionRef} className="px-6 pt-16 sm:px-8">
        <div className="mx-auto flex max-w-[820px] flex-col items-center text-center">
          <div className="flex items-center gap-1.5 rounded-full border bg-card px-4 py-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="size-3.5" />
            AI-powered website audits
          </div>

          <h1 className="mt-5 text-pretty font-display text-[2.5rem] leading-[1.08] font-bold tracking-tight sm:text-[3.6rem]">
            Find exactly what's hurting your website — in under 60 seconds.
          </h1>

          <p className="mx-auto mt-4 max-w-[56ch] text-base text-foreground/70 sm:text-lg">
            Accessibility, SEO, performance, copy, and visual design — in one report.
          </p>

          <form onSubmit={handleSubmit} className="mt-8 w-full max-w-lg" noValidate>
            <div className="flex flex-col gap-2 rounded-2xl border bg-card p-2 shadow-xs sm:flex-row sm:items-center sm:gap-2.5 sm:rounded-full sm:py-2 sm:pr-2 sm:pl-5">
              <div className="relative flex flex-1 items-center gap-2.5 px-3 sm:px-0">
                <Globe className="size-[18px] shrink-0 text-muted-foreground" />
                <div className="relative flex-1">
                  <Input
                    ref={heroInputRef}
                    type="text"
                    inputMode="url"
                    autoComplete="url"
                    value={url}
                    disabled={isLoading}
                    onChange={(event) => setUrl(event.target.value)}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setIsFocused(false)}
                    aria-invalid={validationError ? true : undefined}
                    aria-label="Website URL"
                    className="h-11 flex-1 border-none bg-transparent p-0 text-base shadow-none focus-visible:ring-0"
                  />
                  {showTypedOverlay && (
                    <div
                      aria-hidden
                      className="pointer-events-none absolute inset-0 flex items-center text-base text-foreground"
                    >
                      {typedUrl}
                      <span className="animate-pulse">|</span>
                    </div>
                  )}
                </div>
              </div>
              <Button
                type="submit"
                size="lg"
                disabled={isLoading}
                className="cta-pulse h-[46px] w-full text-[14px] sm:w-auto sm:shrink-0"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Auditing…
                  </>
                ) : (
                  <>
                    Analyze Website
                    <ArrowRight className="size-[15px]" />
                  </>
                )}
              </Button>
            </div>

            {validationError && <p className="mt-3 text-sm text-destructive">{validationError}</p>}

            {apiError && (
              <Alert variant="destructive" className="mt-3 text-left">
                <AlertCircle />
                <AlertTitle>Audit failed</AlertTitle>
                <AlertDescription>{apiError}</AlertDescription>
              </Alert>
            )}
          </form>

          <ul className="mt-[18px] flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
            {TRUST_BULLETS.map((label) => (
              <li key={label} className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <Check className="size-3.5 text-link" strokeWidth={2.75} />
                {label}
              </li>
            ))}
          </ul>

          <div className="mt-[22px] flex flex-wrap items-center justify-center gap-2.5">
            <span className="text-[13px] text-muted-foreground">Try:</span>
            {TRY_DOMAINS.map((domain) => (
              <button
                key={domain}
                type="button"
                onClick={() => fillTryDomain(domain)}
                className="rounded-full border bg-card px-3.5 py-[7px] text-[13px] font-semibold transition-colors hover:border-[#DEDED8] hover:bg-[#F2F1EB]"
              >
                {domain}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Dashboard preview — mocked, but reuses the real score-band color tokens
          so it reads as an honest preview. Count-up + bar fill trigger once
          scrolled into view. */}
      <section id="preview" ref={previewRef} className="px-6 pt-24 sm:px-8">
        <div className="mx-auto max-w-[1080px] text-center">
          <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            What you'll get
          </div>
          <h2 className="mt-2.5 font-display text-3xl font-bold tracking-tight sm:text-[38px]">
            A complete report in under a minute
          </h2>

          <div
            className="mt-9 rounded-[26px] p-7 text-left shadow-[0_50px_100px_-50px_rgba(20,22,28,0.55)] sm:p-9"
            style={{ background: "linear-gradient(165deg, #1C1F25 0%, #15171C 60%, #121317 100%)" }}
          >
            <div className="relative overflow-hidden rounded-[18px] border border-white/[0.07] bg-white/[0.035] p-7 sm:px-[30px] sm:py-7">
              <div
                aria-hidden
                className="pointer-events-none absolute -top-[70px] -left-[50px] size-[220px] rounded-full opacity-60"
                style={{
                  background: "radial-gradient(circle, oklch(85% 0.19 128 / 0.16), transparent 70%)",
                }}
              />
              <div className="relative flex items-start justify-between gap-6">
                <div>
                  <div className="text-[11px] font-semibold tracking-[0.15em] text-ink-muted uppercase">
                    Overall score
                  </div>
                  <div className="mt-2.5 flex items-baseline gap-1.5">
                    <span className="font-display text-6xl leading-[0.82] font-bold tracking-tight text-primary sm:text-[84px]">
                      {overallScore}
                    </span>
                    <span className="text-[15px] font-normal text-ink-muted">/100</span>
                  </div>
                </div>
                <span className="rounded-full bg-white/[0.08] px-4 py-2 text-xs font-semibold whitespace-nowrap text-ink-foreground/80">
                  Sample report
                </span>
              </div>
            </div>

            <div className="mt-[18px] rounded-[18px] border border-white/[0.07] bg-white/[0.035] px-6 sm:px-[30px]">
              {MOCK_CATEGORY_SCORES.map(({ label, score }, index) => {
                const band = getScoreBand(score)
                return (
                  <div
                    key={label}
                    className={`flex items-center gap-5 py-3.5 ${
                      index < MOCK_CATEGORY_SCORES.length - 1 ? "border-b border-white/[0.06]" : ""
                    }`}
                  >
                    <span className="w-[100px] shrink-0 text-sm font-medium text-ink-foreground">{label}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
                      <div
                        className={`h-full rounded-full transition-[width] duration-[1100ms] ease-out ${scoreBandIndicatorClass[band]}`}
                        style={{ width: previewInView ? `${score}%` : "0%" }}
                      />
                    </div>
                    <span className="font-display w-[34px] shrink-0 text-right text-lg font-bold text-ink-foreground">
                      {score}
                    </span>
                  </div>
                )
              })}
            </div>

            <div className="mt-[18px] grid grid-cols-1 gap-[18px] sm:grid-cols-[1.2fr_1fr]">
              <div className="rounded-[18px] border border-white/[0.07] bg-white/[0.035] p-5">
                <div className="text-[11px] font-semibold tracking-[0.12em] text-[oklch(68%_0.16_22)] uppercase">
                  Critical findings
                </div>
                <div className="mt-3 flex flex-col gap-2.5">
                  {CRITICAL_FINDINGS.map((finding) => (
                    <div key={finding} className="text-sm text-ink-foreground/90">
                      {finding}
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                {PREVIEW_STATS.map((stat) => (
                  <div key={stat.label} className="rounded-xl border border-white/[0.08] bg-white/[0.04] p-3.5">
                    <div
                      className={`font-display text-[22px] leading-none font-bold ${
                        stat.accent ? "text-primary" : "text-ink-foreground"
                      }`}
                    >
                      {stat.value}
                    </div>
                    <div className="mt-1 text-[11px] text-ink-muted">{stat.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Illustrative example — your real audit will look like this, scored from your actual page.
          </p>
        </div>
      </section>

      {/* See exactly what you'll receive — mockups matching the real Results page's own card style. */}
      <section className="px-6 pt-[110px] sm:px-8">
        <div className="mx-auto max-w-[1080px]">
          <div className="text-center">
            <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              The real product
            </div>
            <h2 className="mt-2.5 font-display text-[34px] font-bold tracking-tight">
              See exactly what you'll receive
            </h2>
          </div>

          <div className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Accessibility */}
            <div className="rounded-[22px] border bg-card p-8">
              <div className="flex items-center gap-2.5 font-display text-xl font-bold">
                <span className="flex size-8 items-center justify-center rounded-[9px] bg-secondary">
                  <SlidersHorizontal className="size-4" />
                </span>
                Accessibility
              </div>
              <div className="mt-5 flex items-baseline justify-between">
                <div className="font-display flex items-baseline gap-1">
                  <span className="text-5xl font-bold tracking-tight">70</span>
                  <span className="text-sm text-muted-foreground">/100</span>
                </div>
                <span className="text-[13px] font-semibold text-[var(--status-needs-work)]">Needs work</span>
              </div>
              <div className="mt-3.5 h-[5px] overflow-hidden rounded-full bg-secondary">
                <div className={`h-full rounded-full ${scoreBandIndicatorClass["needs-work"]}`} style={{ width: "70%" }} />
              </div>
              <div className="mt-5 rounded-[13px] border p-4">
                <div className="flex items-center justify-between gap-2.5">
                  <span className="text-sm font-semibold">24 images missing alt text</span>
                  <div className="flex gap-1.5">
                    <span className="rounded-full border px-2.5 py-[3px] text-[10px] font-semibold">Quick win</span>
                    <span className="rounded-full bg-destructive px-2.5 py-[3px] text-[10px] font-semibold text-white">
                      high
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Performance */}
            <div className="rounded-[22px] border bg-card p-8">
              <div className="flex items-center gap-2.5 font-display text-xl font-bold">
                <span className="flex size-8 items-center justify-center rounded-[9px] bg-secondary">
                  <Gauge className="size-4" />
                </span>
                Performance
              </div>
              <div className="mt-5 flex items-baseline justify-between">
                <div className="font-display flex items-baseline gap-1">
                  <span className="text-5xl font-bold tracking-tight text-destructive">36</span>
                  <span className="text-sm text-muted-foreground">/100</span>
                </div>
                <span className="text-[13px] font-semibold text-destructive">Poor</span>
              </div>
              <div className="mt-3.5 h-[5px] overflow-hidden rounded-full bg-[oklch(95%_0.02_22)]">
                <div className={`h-full rounded-full ${scoreBandIndicatorClass.poor}`} style={{ width: "36%" }} />
              </div>
              <div className="mt-5 rounded-[13px] border border-l-[3px] border-l-destructive p-4">
                <div className="flex items-center justify-between gap-2.5">
                  <span className="text-sm font-semibold">Slow LCP (4.8s)</span>
                  <div className="flex gap-1.5">
                    <span className="rounded-full border px-2.5 py-[3px] text-[10px] font-semibold">Involved</span>
                    <span className="rounded-full bg-destructive px-2.5 py-[3px] text-[10px] font-semibold text-white">
                      high
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Copy Review */}
            <div className="rounded-[22px] border bg-card p-8">
              <div className="flex items-center gap-2.5 font-display text-xl font-bold">
                <span className="flex size-8 items-center justify-center rounded-[9px] bg-secondary">
                  <FileText className="size-4" />
                </span>
                Copy Review
              </div>
              <div className="mt-5 flex items-baseline justify-between">
                <div className="font-display flex items-baseline gap-1">
                  <span className="text-5xl font-bold tracking-tight">63</span>
                  <span className="text-sm text-muted-foreground">/100</span>
                </div>
                <span className="text-[13px] font-semibold text-[var(--status-needs-work)]">Needs work</span>
              </div>
              <div className="mt-3.5 h-[5px] overflow-hidden rounded-full bg-secondary">
                <div className={`h-full rounded-full ${scoreBandIndicatorClass["needs-work"]}`} style={{ width: "63%" }} />
              </div>
              <div className="mt-5 rounded-[13px] border p-4">
                <span className="inline-block rounded-full bg-secondary px-2.5 py-[3px] text-[11px] font-semibold">
                  Value Proposition Clarity
                </span>
                <p className="mt-2 text-[13px] text-muted-foreground">
                  Headline lacks a clear value proposition for first-time visitors.
                </p>
              </div>
            </div>

            {/* Prioritized Action List */}
            <div className="rounded-[22px] border bg-card p-8">
              <div className="font-display text-xl font-bold">Prioritized Action List</div>
              <div className="mt-[18px] flex flex-col gap-2.5">
                {["Add alt text to product images", "Compress hero image to cut LCP", "Rewrite headline around a specific value prop"].map(
                  (item, index) => (
                    <div key={item} className="flex items-center gap-3">
                      <span className="font-display flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                        {index + 1}
                      </span>
                      <span className="text-sm text-foreground/80">{item}</span>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            A preview of the real Results page — same score cards and action list you'll get after every audit.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="px-6 pt-[110px] sm:px-8">
        <div className="mx-auto max-w-[1080px]">
          <div className="text-center">
            <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              How it works
            </div>
            <h2 className="mt-2.5 font-display text-[34px] font-bold tracking-tight">Four agents, one action plan</h2>
          </div>
          <div className="mt-10 grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-4">
            {PROCESS_STEPS.map(({ icon: Icon, tool, title, description, inverted }) => (
              <div
                key={title}
                className={`rounded-[20px] p-6 transition-transform duration-300 ease-out hover:-translate-y-1 hover:shadow-xl ${
                  inverted ? "bg-ink" : "border bg-card"
                }`}
              >
                <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                  <Icon className="size-[21px]" />
                </div>
                <div
                  className={`mt-[18px] text-[11px] font-semibold tracking-[0.1em] uppercase ${
                    inverted ? "text-ink-muted" : "text-muted-foreground"
                  }`}
                >
                  {tool}
                </div>
                <div className={`font-display mt-1 text-[19px] font-bold ${inverted ? "text-ink-foreground" : ""}`}>
                  {title}
                </div>
                <p className={`mt-2 text-sm leading-[1.55] ${inverted ? "text-ink-muted" : "text-muted-foreground"}`}>
                  {description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trusted analysis engine */}
      <section className="mt-[110px] border-y bg-secondary/40 px-6 py-16 sm:px-8">
        <div className="mx-auto flex max-w-[820px] flex-col items-center gap-5 text-center">
          <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Trusted analysis engine
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {POWERED_BY.map((name) => (
              <span
                key={name}
                className={`rounded-full border px-[22px] py-[11px] text-sm font-semibold ${
                  name === "Gemini"
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-ink bg-ink text-ink-foreground"
                }`}
              >
                {name}
              </span>
            ))}
          </div>
          <p className="max-w-[52ch] text-[15px] leading-relaxed text-muted-foreground">
            5 specialized agents analyze your site in parallel — 150+ signals, real browser rendering — then Gemini
            turns the findings into a prioritized action list.
          </p>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative overflow-hidden bg-ink px-6 py-16 text-center sm:px-8">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-[100px] left-1/2 h-[280px] w-[420px] -translate-x-1/2 rounded-full"
          style={{ background: "radial-gradient(circle, oklch(85% 0.19 128 / 0.2), transparent 70%)" }}
        />
        <h2 className="relative font-display text-[2.2rem] leading-[1.1] font-bold tracking-tight text-ink-foreground">
          Ready to audit your website?
        </h2>
        <p className="relative mt-3.5 text-base text-ink-muted">
          Analyze for free in under 60 seconds. No signup required.
        </p>
        <button
          type="button"
          onClick={focusHero}
          className="cta-pulse relative mt-7 inline-flex items-center gap-2.5 rounded-full bg-primary px-[30px] py-4 text-[15px] font-semibold text-primary-foreground transition hover:brightness-105"
        >
          Analyze Website
          <ArrowRight className="size-4" />
        </button>
      </section>

      <footer className="px-6 py-12 sm:px-8">
        <div className="mx-auto flex max-w-[1080px] flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <div className="flex size-[26px] items-center justify-center rounded-lg bg-primary">
                <Zap className="size-3.5 text-primary-foreground" />
              </div>
              <span className="font-display text-lg font-bold">AuditPilot</span>
            </div>
            <p className="mt-3 max-w-[26ch] text-[13px] leading-relaxed text-muted-foreground">
              Built for designers, agencies, and product teams shipping better websites.
            </p>
          </div>
          <div className="flex gap-2.5 text-[13px] font-medium">
            <a href="#how-it-works" className="text-foreground/70 hover:text-foreground">
              Features
            </a>
            <span className="text-border">·</span>
            <a href="#preview" className="text-foreground/70 hover:text-foreground">
              Sample report
            </a>
          </div>
        </div>
        <div className="mx-auto mt-8 max-w-[1080px] border-t pt-6 text-[12px] text-muted-foreground/70">
          © {new Date().getFullYear()} AuditPilot
        </div>
      </footer>
    </main>
  )
}
