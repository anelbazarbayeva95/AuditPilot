import { CircleOff } from "lucide-react"

/**
 * Polished replacement for a raw "Analysis failed: <stack trace>" summary.
 * Used wherever a CategoryResult comes back with score=null (Performance,
 * Copy, or Visual failing doesn't take down the rest of the audit — see
 * backend/orchestrator.py's run_agent_safely). The real error is still
 * available, just tucked behind an optional disclosure instead of being the
 * first thing a reader sees.
 */
export function UnavailablePanel({
  explanation,
  technicalDetail,
}: {
  explanation: string
  technicalDetail?: string | null
}) {
  return (
    <div className="flex flex-1 flex-col items-start gap-3 rounded-lg border border-dashed bg-muted/30 p-4">
      <div className="flex items-center gap-2">
        <CircleOff className="size-4 text-muted-foreground" />
        <span className="text-sm font-semibold">Analysis unavailable</span>
      </div>
      <p className="text-sm text-muted-foreground">{explanation}</p>
      {technicalDetail && (
        <details className="w-full text-xs text-muted-foreground print:hidden">
          <summary className="cursor-pointer select-none font-medium hover:text-foreground">
            Technical details
          </summary>
          <p className="mt-1.5 max-h-32 overflow-y-auto rounded bg-muted p-2 font-mono break-words">
            {technicalDetail}
          </p>
        </details>
      )}
    </div>
  )
}
