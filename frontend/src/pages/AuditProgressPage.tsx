import { useEffect, useRef, useState } from "react"
import { AlertCircle, CheckCircle2, Circle, Loader2, ScanSearch, Zap } from "lucide-react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ApiError, getReportJob } from "@/lib/api"
import { formatDisplayUrl } from "@/lib/utils"
import type { ReportJob, ReportJobStep, StepState } from "@/types/audit"

const POLL_INTERVAL_MS = 1200

/** Exported so the homepage's "Watch it audit, live" demo can reuse the exact
 *  same step labels/order instead of drifting out of sync with the real flow. */
export const STEP_LABELS: Record<ReportJobStep, string> = {
  scrape: "Scraping the page",
  accessibility: "Accessibility checks",
  seo: "SEO checks",
  copy: "Copy review (Gemini)",
  performance: "Performance (Lighthouse)",
  visual: "Visual review (screenshots + Gemini)",
}

export const STEP_ORDER: ReportJobStep[] = [
  "scrape",
  "accessibility",
  "seo",
  "copy",
  "performance",
  "visual",
]

interface LocationState {
  jobId: string
  url: string
}

function isLocationState(state: unknown): state is LocationState {
  if (!state || typeof state !== "object") return false
  const candidate = state as Partial<LocationState>
  return typeof candidate.jobId === "string" && typeof candidate.url === "string"
}

function StepIcon({ state }: { state: StepState }) {
  switch (state) {
    case "completed":
      return <CheckCircle2 className="size-[13px] text-primary" strokeWidth={3} />
    case "failed":
      return <AlertCircle className="size-[13px] text-destructive" strokeWidth={3} />
    case "running":
      return <Loader2 className="size-[13px] animate-spin text-primary" strokeWidth={3} />
    default:
      return <Circle className="size-1.5 fill-border text-border" />
  }
}

export function AuditProgressPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [job, setJob] = useState<ReportJob | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const navigatedRef = useRef(false)

  const state = isLocationState(location.state) ? location.state : null

  useEffect(() => {
    if (!state) return

    let cancelled = false

    async function poll() {
      try {
        const current = await getReportJob(state!.jobId)
        if (cancelled) return
        setJob(current)

        if (current.status === "completed" && current.result && !navigatedRef.current) {
          navigatedRef.current = true
          navigate("/results", { state: { report: current.result, url: state!.url } })
        }
      } catch (err) {
        if (cancelled) return
        setPollError(
          err instanceof ApiError ? err.message : "Lost connection to the AuditPilot API."
        )
      }
    }

    poll()
    const interval = setInterval(() => {
      if (!navigatedRef.current) poll()
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [state, navigate])

  if (!state) {
    return <Navigate to="/" replace />
  }

  const failed = job?.status === "failed" || !!pollError

  // Real completion accounting — derived from actual per-step status, not
  // simulated. A step counts once its agent has actually finished (or failed).
  // "scrape" isn't one of the 5 agents (Accessibility/SEO/Copy/Performance/
  // Visual) — it's the prep step that feeds them — so it's excluded from the
  // "Agent X of Y" count even though it still counts toward the overall %.
  const AGENT_STEPS: ReportJobStep[] = STEP_ORDER.filter((step) => step !== "scrape")
  const completedCount = STEP_ORDER.filter((step) => {
    const s = job?.progress[step] ?? "pending"
    return s === "completed" || s === "failed"
  }).length
  const runningStep = STEP_ORDER.find((step) => (job?.progress[step] ?? "pending") === "running")
  const runningAgentIndex = runningStep ? AGENT_STEPS.indexOf(runningStep) : -1
  const pct = job ? Math.round((completedCount / STEP_ORDER.length) * 100) : 0
  const agentLabel =
    completedCount >= STEP_ORDER.length
      ? "Finishing up"
      : runningStep === "scrape"
        ? "Preparing page"
        : runningAgentIndex >= 0
          ? `Agent ${runningAgentIndex + 1} of ${AGENT_STEPS.length}`
          : "Starting…"

  return (
    <main className="flex min-h-svh flex-col" style={{ background: "linear-gradient(180deg, #FAFAF9 0%, #F6F6F5 340px, #FFFFFF 720px)" }}>
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
        <button
          type="button"
          onClick={() => navigate("/")}
          className="rounded-full border px-4 py-2 text-xs font-semibold text-muted-foreground transition-colors hover:bg-secondary"
        >
          Cancel
        </button>
      </header>

      <div className="flex flex-1 items-center justify-center px-4 py-16 sm:px-6">
        <div className="w-full max-w-[680px]">
          <div className="mb-7 text-center">
            <div className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Auditing in progress
            </div>
          </div>

          <div className="rounded-[26px] border bg-card p-9 shadow-[0_40px_80px_-44px_rgba(20,22,28,0.3)] sm:p-11">
            <div className="flex items-center gap-3.5">
              <div className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-secondary">
                <ScanSearch className="size-[17px] text-muted-foreground" />
              </div>
              <div
                className="min-w-0 truncate font-display text-xl font-bold tracking-tight"
                title={state.url}
              >
                Auditing {formatDisplayUrl(state.url)}
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between">
              <span className="text-[13px] font-semibold text-muted-foreground">{agentLabel}</span>
              <span className="font-display text-sm font-bold">{pct}%</span>
            </div>
            <div className="mt-2 h-[5px] overflow-hidden rounded-full bg-secondary">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
                style={{ width: `${pct}%` }}
              />
            </div>

            <ul className="mt-7 flex flex-col gap-5">
              {STEP_ORDER.map((step) => {
                const stepState = job?.progress[step] ?? "pending"
                const done = stepState === "completed"
                const active = stepState === "running"
                return (
                  <li key={step} className="flex items-center gap-3.5">
                    <span
                      className={`flex size-[26px] shrink-0 items-center justify-center rounded-full border-2 ${
                        done || active
                          ? "border-primary"
                          : stepState === "failed"
                            ? "border-destructive"
                            : "border-border"
                      }`}
                    >
                      <StepIcon state={stepState} />
                    </span>
                    <span
                      className={`text-base ${done || active ? "text-foreground" : "text-muted-foreground/60"}`}
                    >
                      {STEP_LABELS[step]}
                    </span>
                  </li>
                )
              })}
            </ul>

            {failed && (
              <Alert variant="destructive" className="mt-6">
                <AlertCircle />
                <AlertTitle>Audit failed</AlertTitle>
                <AlertDescription>
                  {pollError ?? job?.error ?? "Something went wrong running this audit."}
                </AlertDescription>
              </Alert>
            )}

            {failed && (
              <Button variant="outline" className="mt-4" onClick={() => navigate("/")}>
                Back to input
              </Button>
            )}
          </div>

          <p className="mt-4 text-center text-[13px] text-muted-foreground">
            This can take up to a minute depending on the site — each step above updates as its agent actually
            finishes.
          </p>
        </div>
      </div>
    </main>
  )
}
