import { useEffect, useState } from "react"
import { ArrowLeft, Download, Gauge, Loader2, Search, ScanSearch, SlidersHorizontal, Zap } from "lucide-react"
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom"

import { CategoryCard } from "@/components/audit/CategoryCard"
import { ChartsSection } from "@/components/audit/ChartsSection"
import { CopyReviewCard } from "@/components/audit/CopyReviewCard"
import { ExecutiveSummary } from "@/components/audit/ExecutiveSummary"
import { GroupedFindingsSection, findingGroupAnchorId } from "@/components/audit/GroupedFindingsSection"
import { MethodologyPanel } from "@/components/audit/MethodologyPanel"
import { PrioritizedRecommendations } from "@/components/audit/PrioritizedRecommendations"
import { ResultsSidebar, type SectionId } from "@/components/audit/ResultsSidebar"
import { ResultsSubNav, type SubNavItem } from "@/components/audit/ResultsSubNav"
import { VisualReviewCard } from "@/components/audit/VisualReviewCard"
import { Button } from "@/components/ui/button"
import { ApiError, downloadReportPdf, getReportJob } from "@/lib/api"
import { groupFindingsByTitle } from "@/lib/issueText"
import { isCopyRawData, isVisualRawData } from "@/lib/rawData"
import { actionsOf } from "@/lib/summary"
import type { StructuredAuditReport } from "@/types/audit"

interface LocationState {
  report: StructuredAuditReport
  url: string
}

function isLocationState(state: unknown): state is LocationState {
  if (!state || typeof state !== "object") return false
  const candidate = state as Partial<LocationState>
  return typeof candidate.url === "string" && !!candidate.report
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

const SUB_NAV_TITLE: Record<SectionId, string> = {
  summary: "In this section",
  visual: "In this section",
  accessibility: "Issues in this section",
  seo: "Issues in this section",
  performance: "Issues in this section",
  copy: "In this section",
  charts: "In this section",
  actions: "Items in this list",
  methodology: "In this section",
}

/**
 * Resolves which report to show, then renders it.
 *
 * Arriving from the progress page, the report is already in router state. On
 * a refresh or a revisited link that state is gone, so the report is
 * re-fetched from the backend by the `?job=` id — it keeps finished jobs for
 * a limited time (JOB_RETENTION_SECONDS), after which the visitor is told to
 * re-run rather than shown anything stale or placeholder.
 */
export function AuditResultsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = searchParams.get("job")
  const fromState = isLocationState(location.state) ? location.state : null
  const [fetched, setFetched] = useState<LocationState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (fromState || !jobId) return
    let cancelled = false

    getReportJob(jobId)
      .then((job) => {
        if (cancelled) return
        if (job.status === "completed" && job.result) {
          setFetched({ report: job.result, url: job.url })
        } else if (job.status === "failed") {
          setLoadError(job.error ?? "This audit failed.")
        } else {
          navigate(`/progress?job=${encodeURIComponent(jobId)}`, { replace: true })
        }
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(err instanceof ApiError ? err.message : "Couldn't load this report.")
      })

    return () => {
      cancelled = true
    }
  }, [fromState, jobId, navigate])

  const resolved = fromState ?? fetched
  if (resolved) return <ResultsView report={resolved.report} url={resolved.url} />
  if (!jobId) return <Navigate to="/" replace />
  return <ReportStatus error={loadError} onNewAudit={() => navigate("/")} />
}

function ReportStatus({ error, onNewAudit }: { error: string | null; onNewAudit: () => void }) {
  return (
    <main className="flex min-h-svh items-center justify-center px-4">
      <div className="w-full max-w-[460px] rounded-[20px] border bg-card p-8 text-center" role="status">
        {error ? (
          <>
            <h1 className="font-display text-lg font-bold">Report unavailable</h1>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
            <Button className="mt-5" onClick={onNewAudit}>
              Run a new audit
            </Button>
          </>
        ) : (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading report…
          </div>
        )}
      </div>
    </main>
  )
}

/**
 * "Docs Layout" Results page: a compact shared header, a left rail that
 * switches which section is mounted (click-to-navigate, not scroll-spy —
 * only the active section exists in the DOM at a time), and a right rail of
 * jump links into whatever sub-blocks/issues that section actually has.
 */
function ResultsView({ report, url }: LocationState) {
  const navigate = useNavigate()
  const [active, setActive] = useState<SectionId>("summary")
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  async function handleDownloadPdf() {
    setDownloadError(null)
    setIsDownloading(true)
    try {
      const blob = await downloadReportPdf(url, report)
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = objectUrl
      link.download = `auditpilot-${hostnameOf(url)}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.message : "Something went wrong generating the PDF.")
    } finally {
      setIsDownloading(false)
    }
  }

  const visualData = isVisualRawData(report.visual.raw_data) ? report.visual.raw_data : null
  const copyData = isCopyRawData(report.copy.raw_data) ? report.copy.raw_data : null

  function selectSection(id: SectionId) {
    setActive(id)
    window.scrollTo({ top: 0 })
  }

  const subItems: SubNavItem[] = (() => {
    switch (active) {
      case "summary":
        return [
          { id: "summary-health", label: "Overall health" },
          { id: "summary-messages", label: "What this means" },
          { id: "summary-top-issue", label: "Start here" },
          { id: "summary-also-fixing", label: "Then" },
          { id: "summary-strengths", label: "Key strengths" },
        ]
      case "visual":
        return [
          visualData && visualData.strengths.length > 0 ? { id: "visual-strengths", label: "Strengths" } : null,
          visualData && visualData.weaknesses.length > 0 ? { id: "visual-weaknesses", label: "Weaknesses" } : null,
          visualData && visualData.recommendations.length > 0
            ? { id: "visual-recommendations", label: "Recommendations" }
            : null,
        ].filter((item): item is SubNavItem => item !== null)
      case "accessibility":
        // Grouped by check (e.g. "Empty buttons · 8") rather than one entry
        // per raw finding — repeated findings share a title, so a naive
        // per-recommendation list would repeat "Empty Button" many times.
        return groupFindingsByTitle(report.accessibility.recommendations).map((group) => ({
          id: findingGroupAnchorId("accessibility", group.title),
          label:
            group.occurrences.length > 1
              ? `${group.title} · ${group.occurrences.length}`
              : group.title,
        }))
      case "seo":
        // Same grouping as Accessibility — SEO's per-image/per-tag checks
        // (e.g. "Missing Alt Text") can also fire more than once per page.
        return groupFindingsByTitle(report.seo.recommendations).map((group) => ({
          id: findingGroupAnchorId("seo", group.title),
          label:
            group.occurrences.length > 1
              ? `${group.title} · ${group.occurrences.length}`
              : group.title,
        }))
      case "performance":
        return report.performance.recommendations.map((r, i) => ({ id: `performance-${i + 1}`, label: r.title }))
      case "copy":
        return [
          copyData && copyData.strengths.length > 0 ? { id: "copy-strengths", label: "Strengths" } : null,
          copyData && copyData.weaknesses.length > 0 ? { id: "copy-weaknesses", label: "Weaknesses" } : null,
          copyData && copyData.recommendations.length > 0
            ? { id: "copy-recommendations", label: "Recommendations" }
            : null,
        ].filter((item): item is SubNavItem => item !== null)
      case "charts":
        return [
          { id: "chart-scores", label: "Category Scores" },
          { id: "chart-severity", label: "Issues by Severity" },
        ]
      case "actions":
        return actionsOf(report).map((action, i) => ({
          id: `action-${i + 1}`,
          label: `${i + 1} · ${action.title}`,
        }))
      case "methodology":
        return [
          { id: "methodology-run", label: "Run conditions" },
          { id: "methodology-scoring", label: "Scoring model" },
          { id: "methodology-coverage", label: "Coverage by category" },
          { id: "methodology-scope", label: "Scope limitations" },
        ]
      default:
        return []
    }
  })()

  return (
    <div
      className="min-h-svh print:block"
      style={{ background: "linear-gradient(180deg, #FAFAF9 0%, #F6F6F5 340px, #FFFFFF 720px)" }}
    >
      <header className="border-b px-5 py-4 print:hidden sm:px-8">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between">
          <button
            type="button"
            onClick={() => navigate("/")}
            className="flex items-center gap-2.5 rounded-lg text-left transition-opacity hover:opacity-80"
            aria-label="Back to AuditPilot home"
          >
            <div className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-primary">
              <Zap className="size-4 text-primary-foreground" />
            </div>
            <span className="font-display text-[17px] font-bold">AuditPilot</span>
            <span className="ml-1 flex items-center gap-1.5 border-l pl-3.5 text-xs text-muted-foreground">
              <ScanSearch className="size-2.5 opacity-60" />
              {hostnameOf(url)}
            </span>
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownloadPdf}
              disabled={isDownloading}
              className="flex items-center gap-1.5 rounded-full border px-4 py-2 text-xs font-semibold text-foreground/80 transition hover:bg-secondary disabled:opacity-60"
            >
              {isDownloading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Download className="size-3.5" />
              )}
              {isDownloading ? "Preparing…" : "Download PDF"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/")}
              className="flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground transition hover:brightness-105"
            >
              <ArrowLeft className="size-3.5" />
              New Audit
            </button>
          </div>
        </div>
        {downloadError && (
          <div className="mx-auto mt-2 max-w-[1440px] text-xs text-destructive">{downloadError}</div>
        )}
      </header>

      <div className="mx-auto grid max-w-[1440px] grid-cols-1 md:grid-cols-[220px_1fr] lg:grid-cols-[220px_1fr_220px]">
        <ResultsSidebar report={report} active={active} onSelect={selectSection} />

        <main className="min-w-0 px-5 py-10 sm:px-10 md:max-w-[820px] print:max-w-none print:px-0 print:py-0">
          {active === "summary" && (
            <ExecutiveSummary report={report} url={url} onViewActions={() => selectSection("actions")} />
          )}
          {active === "visual" && (
            <VisualReviewCard
              result={report.visual}
              screenshotViewportBase64={report.screenshot_viewport_base64}
              screenshotFullPageBase64={report.screenshot_full_page_base64}
              screenshotQuality={report.screenshot_quality}
            />
          )}
          {active === "accessibility" && (
            <GroupedFindingsSection
              id="accessibility"
              title="Accessibility"
              icon={<SlidersHorizontal className="size-4" />}
              result={report.accessibility}
              pageUrl={url}
            />
          )}
          {active === "seo" && (
            <GroupedFindingsSection
              id="seo"
              title="SEO"
              icon={<Search className="size-4" />}
              result={report.seo}
              pageUrl={url}
            />
          )}
          {active === "performance" && (
            <CategoryCard
              id="performance"
              title="Performance"
              icon={<Gauge className="size-4" />}
              result={report.performance}
            />
          )}
          {active === "copy" && <CopyReviewCard result={report.copy} />}
          {active === "charts" && (
            <ChartsSection
              summary={report.summary}
              onSelectCategory={(category) => selectSection(category as SectionId)}
              onViewActions={() => selectSection("actions")}
            />
          )}
          {active === "actions" && <PrioritizedRecommendations report={report} pageUrl={url} />}
          {active === "methodology" && <MethodologyPanel report={report} />}
        </main>

        <ResultsSubNav title={SUB_NAV_TITLE[active]} items={subItems} />
      </div>
    </div>
  )
}
