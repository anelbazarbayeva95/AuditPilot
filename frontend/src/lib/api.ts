import type { ReportJob, StructuredAuditReport } from "@/types/audit"

// Configure via a .env file: VITE_API_BASE_URL=http://localhost:8000
const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000"

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

/**
 * Starts a background /report run (Milestone 10) and returns its job id
 * immediately — the Audit Progress page polls getReportJob() for real
 * per-agent completion instead of blocking on one long request.
 */
export async function createReportJob(url: string): Promise<string> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/report/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
  } catch {
    throw new ApiError(
      `Could not reach the AuditPilot API at ${API_BASE_URL}. Is the backend running?`,
      0
    )
  }

  if (!response.ok) {
    throw new ApiError(await extractErrorDetail(response), response.status)
  }

  const body = (await response.json()) as { job_id: string }
  return body.job_id
}

/** Fetches the current state of a background report job. */
export async function getReportJob(jobId: string): Promise<ReportJob> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/report/jobs/${jobId}`)
  } catch {
    throw new ApiError(
      `Could not reach the AuditPilot API at ${API_BASE_URL}. Is the backend running?`,
      0
    )
  }

  if (!response.ok) {
    throw new ApiError(await extractErrorDetail(response), response.status)
  }

  return (await response.json()) as ReportJob
}

/**
 * Downloads the real PDF export for a completed audit — calls POST
 * /report/pdf/full with exactly the StructuredAuditReport the Results page
 * already has in memory (all five agents + screenshots), and returns the
 * raw PDF bytes as a Blob for the caller to save.
 */
export async function downloadReportPdf(url: string, report: StructuredAuditReport): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/report/pdf/full`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, report }),
    })
  } catch {
    throw new ApiError(
      `Could not reach the AuditPilot API at ${API_BASE_URL}. Is the backend running?`,
      0
    )
  }

  if (!response.ok) {
    throw new ApiError(await extractErrorDetail(response), response.status)
  }

  return response.blob()
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string") return body.detail
    if (Array.isArray(body.detail)) {
      // FastAPI/Pydantic validation errors (422): array of {msg, loc, ...}
      return body.detail
        .map((entry) =>
          typeof entry === "object" && entry !== null && "msg" in entry
            ? String((entry as { msg: unknown }).msg)
            : JSON.stringify(entry)
        )
        .join("; ")
    }
    return `Request failed with status ${response.status}`
  } catch {
    return `Request failed with status ${response.status}`
  }
}
