"""
AuditPilot FastAPI application entrypoint.

Exposes the health endpoint and (future) audit endpoints. No business logic
lives here — routes delegate to the orchestrator.
"""

from __future__ import annotations

import logging
import os

from dotenv import find_dotenv, load_dotenv

# Stage-level pipeline logging (agent start/done/failed, Gemini/Lighthouse/
# screenshot-capture timing) is emitted via `logging.getLogger(__name__)` in
# report.py, jobs.py, orchestrator.py, gemini_client.py, lighthouse_runner.py,
# and screenshot.py. Configure this *before* anything below logs, so startup
# diagnostics (dotenv resolution, key presence) aren't lost to the default
# "last resort" handler. Override with LOG_LEVEL if needed.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment/config resolution diagnostics.
#
# GEMINI_API_KEY can reach this process two ways: (1) already present in the
# process environment when it starts (shell export, IDE run/debug config
# "env" field, systemd/deployment env, etc.), or (2) loaded here from a .env
# file via python-dotenv. These are NOT equally weighted: load_dotenv()'s
# default `override=False` means a key already present in the environment
# always wins — a value in backend/.env (even a blank one) is silently
# ignored if the process already inherited a real key from elsewhere. So
# backend/.env is not necessarily "the" config source; it's only a fallback
# for whatever isn't already set. Do not assume the file is authoritative —
# log what was actually found/used instead of guessing.
#
# Also note python-dotenv's search (find_dotenv, no explicit path) walks up
# from *this file's* directory by default — except when running under a
# debugger/interactively/frozen, where it falls back to searching from the
# current working directory instead (see python-dotenv's find_dotenv()).
# That means the same codebase can load a different (or no) .env file
# depending on whether it's launched via a debugger and what the process's
# cwd is at that moment — worth knowing before concluding a given .env is
# "the" active one.
# ---------------------------------------------------------------------------
_dotenv_path = find_dotenv(usecwd=False)
_logger.info("startup.cwd=%s", os.getcwd())
_logger.info("startup.dotenv_path=%s", _dotenv_path or "<none found>")
_logger.info(
    "startup.dotenv_disabled=%s",
    os.environ.get("PYTHON_DOTENV_DISABLED", "false"),
)

_key_before_dotenv = os.environ.get("GEMINI_API_KEY")
load_dotenv()  # override=False by default: never clobbers an already-set env var
_key_after_dotenv = os.environ.get("GEMINI_API_KEY")
if _key_before_dotenv and _key_before_dotenv == _key_after_dotenv:
    _logger.info("startup.gemini_key_source=process_environment (already set before load_dotenv() ran)")
elif _key_after_dotenv and _key_after_dotenv != _key_before_dotenv:
    _logger.info("startup.gemini_key_source=dotenv_file path=%s", _dotenv_path or "<unknown>")
elif not _key_after_dotenv:
    _logger.info("startup.gemini_key_source=none (not found in process environment or dotenv file)")

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from gemini_client import DEFAULT_MODEL_NAME
from models.schemas import (
    AuditResult,
    HealthResponse,
    PdfReportRequest,
    ReportJob,
    ScrapedPageData,
    ScrapeRequest,
    StructuredAuditReport,
    StructuredPdfReportRequest,
)
from jobs import JobManager
from orchestrator import AuditOrchestrator
from pdf_report import build_pdf_report, build_pdf_report_from_structured
from report import ReportBuilder
from scraper import ScraperError, scrape_website


def _log_gemini_config() -> None:
    """Logs only presence/length/masked-suffix of the key actually resolved — never the key itself."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        suffix = key[-4:] if len(key) >= 4 else key
        _logger.info(
            "gemini_config.present=true gemini_config.length=%d gemini_config.suffix=****%s",
            len(key), suffix,
        )
    else:
        _logger.warning(
            "gemini_config.present=false gemini_config.length=0 gemini_config.suffix=n/a — "
            "Copy Review and Visual Review will fail for every audit until this is set."
        )
    _logger.info("gemini_config.model=%s", DEFAULT_MODEL_NAME)


_log_gemini_config()

# Constructed once at import time — cheap to build (agents don't touch the
# network or require GEMINI_API_KEY until a request actually needs Gemini).
#
# IMPORTANT: GeminiClient.__init__ reads os.environ.get("GEMINI_API_KEY")
# exactly once, at construction time (see gemini_client.py) — not lazily per
# request. These singletons are constructed once, right here, at process
# import time. So if GEMINI_API_KEY is added/changed in the environment or
# .env file *after* this process has already started, nothing here re-reads
# it — the already-constructed CopyAgent/VisualAgent instances keep whatever
# value (or lack thereof) was captured at this moment. A full process
# restart (not just an in-place .env edit, and not a hot code reload unless
# your dev server's reload mechanism also respawns the whole worker process)
# is required to pick up a changed key.
_orchestrator = AuditOrchestrator()
_report_builder = ReportBuilder()
_job_manager = JobManager()

app = FastAPI(
    title="AuditPilot API",
    description="Agentic AI website auditing platform: accessibility, performance, SEO, and messaging analysis.",
    version="0.1.0",
)

# FRONTEND_ORIGINS is a comma-separated allowlist (e.g. the deployed Vercel URL) — unset falls
# back to the local Vite dev server only, never "*", since allow_credentials=True combined with a
# wildcard origin is both rejected by browsers and unsafe if it weren't.
_frontend_origins_env = os.environ.get("FRONTEND_ORIGINS")
if _frontend_origins_env:
    _allowed_origins = [origin.strip() for origin in _frontend_origins_env.split(",") if origin.strip()]
else:
    _allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_logger.info("startup.cors_allowed_origins=%s", _allowed_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Simple liveness check."""
    return HealthResponse()


@app.post("/audit", response_model=ScrapedPageData, tags=["audit"])
async def audit(request: ScrapeRequest) -> ScrapedPageData:
    """Scrape a URL and return structured page data.

    Milestone 1: scraping only (title, meta description, headings, images,
    buttons, links). Accessibility/performance/SEO/copy analysis on top of
    this data lands in later milestones via the orchestrator + agents.
    """
    try:
        return await scrape_website(str(request.url))
    except ScraperError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected failures
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error auditing '{request.url}': {exc}",
        ) from exc


@app.post("/audit/full", response_model=AuditResult, tags=["audit"])
async def audit_full(request: ScrapeRequest) -> AuditResult:
    """Run a full multi-agent audit: scrape the URL, then run Accessibility,
    SEO, and Copy agents in parallel (Milestone 5) and return the aggregated
    result: {overall_score, accessibility, seo, copy}.

    A single agent failing (e.g. Gemini unreachable) does not fail the whole
    request — that category comes back with score: null and an error
    summary. Only a scrape failure (nothing to analyze) surfaces as an
    HTTP error here.

    PerformanceAgent/Lighthouse are not yet included (still a stub).
    """
    try:
        return await _orchestrator.run(str(request.url))
    except ScraperError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected failures
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error auditing '{request.url}': {exc}",
        ) from exc


@app.post("/report/pdf", tags=["audit"])
async def report_pdf(request: PdfReportRequest) -> Response:
    """Render a previously-computed AuditResult (Milestone 8) as a downloadable PDF.

    Takes the result of POST /audit/full (plus optional PerformanceAgent and
    VisualAgent results, since neither is wired into AuditResult yet) rather
    than re-running the audit. Sections: Executive Summary, Accessibility,
    SEO, Copy, Performance, Visual (Milestone 11, with an embedded
    above-the-fold screenshot if provided), and a consolidated
    Recommendations list.
    """
    try:
        pdf_bytes = build_pdf_report(
            str(request.url),
            request.result,
            request.performance,
            request.visual,
            request.screenshot_viewport_base64,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {exc}",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="auditpilot-report.pdf"'},
    )


@app.post("/report/pdf/full", tags=["audit"])
async def report_pdf_full(request: StructuredPdfReportRequest) -> Response:
    """Render a completed job's StructuredAuditReport (all five agents + screenshots
    already combined, as returned by GET /report/jobs/{id}) as a downloadable PDF.

    This is the export path the Results page's "Download PDF" button actually
    calls — unlike /report/pdf (legacy, pre-job-based-flow shape), it takes
    exactly what the frontend already has in memory for a finished audit, no
    reshaping into the older AuditResult format required.
    """
    try:
        pdf_bytes = build_pdf_report_from_structured(str(request.url), request.report)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {exc}",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="auditpilot-report.pdf"'},
    )


@app.post("/report", response_model=StructuredAuditReport, tags=["audit"])
async def report(request: ScrapeRequest) -> StructuredAuditReport:
    """Run all four agents (Accessibility, SEO, Copy, Performance) in parallel
    and return one combined report (Milestone 9):

        {summary, accessibility, seo, performance, copy, recommendations}

    `summary` carries the overall score, per-category scores, and issue
    counts by severity. `recommendations` is every agent's findings merged
    and sorted by severity — the prioritized issue/action-item list.
    """
    try:
        return await _report_builder.build(str(request.url))
    except ScraperError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - guard against unexpected failures
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error building report for '{request.url}': {exc}",
        ) from exc


@app.post("/report/jobs", status_code=status.HTTP_202_ACCEPTED, tags=["audit"])
async def create_report_job(request: ScrapeRequest) -> dict:
    """Start a background /report run (Milestone 10) and return its job id immediately.

    Poll GET /report/jobs/{job_id} for progress; the Audit Progress page uses
    this instead of the blocking POST /report so it can show real per-agent
    completion (scrape -> accessibility/seo/copy/performance) rather than a
    simulated countdown.
    """
    job_id = _job_manager.create_job(str(request.url))
    return {"job_id": job_id, "status": "pending"}


@app.get("/report/jobs/{job_id}", response_model=ReportJob, tags=["audit"])
async def get_report_job(job_id: str) -> ReportJob:
    """Current state of a background report job: status, per-step progress, and the result once completed."""
    job = _job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with id '{job_id}'")
    return job


# TODO: register additional audit routes (report retrieval by id, etc.)
