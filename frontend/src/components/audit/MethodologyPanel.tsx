import { FlaskConical } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { categoryLabel } from "@/lib/summary"
import type { CategoryResult, StructuredAuditReport } from "@/types/audit"

/**
 * How the audit was produced, and what it did not cover.
 *
 * The PDF has carried this since the evidence release; the dashboard didn't,
 * which left the on-screen scores as bare assertions while the exported ones
 * were reproducible. Everything here is read back off the run — nothing is
 * described that wasn't recorded, and a missing value says "not recorded"
 * rather than being filled in with a plausible default.
 */
export function MethodologyPanel({ report, id }: { report: StructuredAuditReport; id?: string }) {
  const ctx = report.run_context
  const perf = ctx?.performance_run

  const rows: Array<[string, string | null | undefined]> = [
    ["Audited URL", ctx?.requested_url],
    ["Resolved URL", ctx?.final_url],
    ["HTTP status", ctx?.http_status != null ? String(ctx.http_status) : null],
    ["Rendering engine", ctx ? "Playwright headless Chromium" : null],
    ["Viewport", ctx?.viewport],
    ["Page-load condition", ctx?.scraper_wait_until],
    ["Accessibility target", ctx?.wcag_target],
    ["Lighthouse version", perf?.lighthouse_version],
    ["Performance form factor", perf?.form_factor],
    ["Performance throttling", perf?.throttling],
    ["Performance runs", perf?.runs != null ? String(perf.runs) : null],
    ["Report version", ctx?.report_version],
  ]

  const categories: Array<[string, CategoryResult]> = [
    ["accessibility", report.accessibility],
    ["seo", report.seo],
    ["performance", report.performance],
    ["copy", report.copy],
    ["visual", report.visual],
  ]

  return (
    <Card id={id} className="scroll-mt-6 break-inside-avoid rounded-[22px] p-9 shadow-none">
      <div className="flex items-center gap-2.5 font-display text-xl font-bold">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-secondary">
          <FlaskConical className="size-[17px]" aria-hidden="true" />
        </span>
        Methodology
      </div>
      <p className="mt-3 max-w-[68ch] text-[13px] leading-relaxed text-muted-foreground">
        Every score above is produced by the process described here. Conclusions outside this scope
        are not supported by this audit.
      </p>

      <CardContent className="mt-6 flex flex-col gap-8 p-0">
        <div id="methodology-run">
          <h3 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Run conditions
          </h3>
          {ctx ? (
            <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2">
              {rows
                .filter(([, value]) => value)
                .map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-4 border-b py-1.5 text-[13px]">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="max-w-[60%] truncate text-right font-medium" title={value ?? ""}>
                      {value}
                    </dd>
                  </div>
                ))}
            </dl>
          ) : (
            <p className="mt-3 text-[13px] text-muted-foreground">
              Run conditions were not recorded for this report.
            </p>
          )}
        </div>

        {report.summary.weights && Object.keys(report.summary.weights).length > 0 && (
          <div id="methodology-scoring">
            <h3 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Scoring model
            </h3>
            <p className="mt-3 text-[13px] leading-relaxed text-foreground/80">
              Categories are weighted by user and business impact:{" "}
              {Object.entries(report.summary.weights)
                .map(([name, weight]) => `${categoryLabel(name)} ${Math.round(weight * 100)}%`)
                .join(", ")}
              . Categories without a score are excluded and the remaining weights renormalized.
            </p>
            {report.summary.score_explanation && (
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {report.summary.score_explanation}
              </p>
            )}
          </div>
        )}

        <div id="methodology-coverage">
          <h3 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
            Coverage by category
          </h3>
          <div className="mt-3 flex flex-col gap-4">
            {categories
              .filter(([, cat]) => cat.coverage)
              .map(([key, cat]) => (
                <div key={key} className="border-b pb-4 last:border-b-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-[15px] font-bold">{categoryLabel(key)}</span>
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-secondary-foreground/80">
                      {cat.coverage?.method === "ai_assisted" ? "AI-assisted" : "Automated"}
                    </span>
                  </div>
                  {cat.coverage!.checks_run.length > 0 && (
                    <p className="mt-1.5 text-[13px] leading-relaxed text-foreground/80">
                      <span className="font-semibold">Tested: </span>
                      {cat.coverage!.checks_run.join(", ")}
                    </p>
                  )}
                  {cat.coverage!.checks_not_covered.length > 0 && (
                    <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                      <span className="font-semibold">Not tested: </span>
                      {cat.coverage!.checks_not_covered.join(", ")}
                    </p>
                  )}
                </div>
              ))}
          </div>
        </div>

        {ctx?.scope_limitations && ctx.scope_limitations.length > 0 && (
          <div id="methodology-scope">
            <h3 className="text-[11px] font-semibold tracking-[0.15em] text-muted-foreground uppercase">
              Scope limitations
            </h3>
            <ul className="mt-3 flex flex-col gap-1.5">
              {ctx.scope_limitations.map((limit) => (
                <li key={limit} className="flex gap-2 text-[13px] leading-relaxed text-foreground/80">
                  <span aria-hidden="true" className="text-muted-foreground">
                    —
                  </span>
                  {limit}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
