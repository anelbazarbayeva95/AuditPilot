"""Background report jobs (Milestone 10) — lets the frontend poll real per-agent progress.

/report (Milestone 9) is one blocking call. JobManager instead starts the
same work in a background asyncio task and exposes incremental progress
("scrape", "accessibility", "seo", "copy", "performance", "visual": pending
-> running -> completed/failed) via an in-memory job store, polled through
GET /report/jobs/{id}.

Each agent's progress flips to completed/failed the instant *that* agent's
own `await` resolves — since they all run concurrently under one
`asyncio.gather`, this reflects real completion order, not a simulated
countdown. "visual" (Milestone 11) covers both screenshot capture and the
Gemini vision call as one step, since a visitor only cares whether visual
analysis is done, not that it's internally a two-stage process.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from agents import AccessibilityAgent, CopyAgent, SEOAgent, VisualAgent
from agents.performance import PerformanceAgent
from agents.suggestions import enrich_with_ai_suggestions
from agents.visual import insufficient_evidence_result
from browser_defaults import DESKTOP_USER_AGENT, DESKTOP_VIEWPORT
from gemini_client import GeminiClient
from models.schemas import (
    AuditCategory,
    AuditResult,
    AuditStatus,
    CategoryResult,
    PerformanceRunConfig,
    ReportJob,
    RunContext,
    ScoreStatus,
    ScrapedPageData,
)
from orchestrator import run_agent_safely
from report import combine_report
from scraper import ScraperError, scrape_website
from screenshot import PageScreenshots, capture_screenshots

# Stated in every report so its conclusions carry their own limits rather than
# implying a breadth the run never had.
SCOPE_LIMITATIONS = [
    "A single URL was audited; other pages and templates were not tested.",
    "One rendered desktop viewport; mobile and other breakpoints were not tested.",
    "Unauthenticated public page only; no logged-in or personalized states.",
    "Automated checks and model judgment only; no manual verification pass.",
    "Performance is a single lab run, not field data from real users.",
]

REPORT_VERSION = "1.0"

ScrapeFn = Callable[[str], Awaitable[ScrapedPageData]]
ScreenshotFn = Callable[[str], Awaitable[PageScreenshots]]

_STEPS = ("scrape", "accessibility", "seo", "copy", "performance", "visual")

logger = logging.getLogger(__name__)


def _build_run_context(
    url: str,
    started_at: datetime,
    page_data: ScrapedPageData,
    performance: CategoryResult,
) -> RunContext:
    """Record how this audit was actually produced.

    Everything here is read back from the run rather than assumed: the URL that
    was really landed on, the status it returned, and the conditions Lighthouse
    reported for itself. That's what makes the report's numbers reproducible
    instead of merely stated.
    """
    performance_run = None
    raw = performance.raw_data or {}
    if isinstance(raw.get("run_config"), dict):
        performance_run = PerformanceRunConfig(**raw["run_config"])

    return RunContext(
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        requested_url=url,
        final_url=page_data.final_url,
        http_status=page_data.http_status,
        viewport=f"{DESKTOP_VIEWPORT['width']}x{DESKTOP_VIEWPORT['height']}",
        user_agent=DESKTOP_USER_AGENT,
        scraper_wait_until="domcontentloaded",
        performance_run=performance_run,
        scope_limitations=list(SCOPE_LIMITATIONS),
        report_version=REPORT_VERSION,
    )


class JobManager:
    """Creates and tracks background /report jobs. Agents/scrape_fn are injectable for tests."""

    def __init__(
        self,
        accessibility_agent: Optional[AccessibilityAgent] = None,
        seo_agent: Optional[SEOAgent] = None,
        copy_agent: Optional[CopyAgent] = None,
        performance_agent: Optional[PerformanceAgent] = None,
        visual_agent: Optional[VisualAgent] = None,
        scrape_fn: Optional[ScrapeFn] = None,
        screenshot_fn: Optional[ScreenshotFn] = None,
        gemini_client: Optional[GeminiClient] = None,
    ) -> None:
        self._accessibility_agent = accessibility_agent or AccessibilityAgent()
        self._seo_agent = seo_agent or SEOAgent()
        self._copy_agent = copy_agent or CopyAgent()
        self._performance_agent = performance_agent or PerformanceAgent()
        self._visual_agent = visual_agent or VisualAgent()
        self._scrape_fn = scrape_fn or scrape_website
        self._screenshot_fn = screenshot_fn or capture_screenshots
        # Separate from any agent's own client — this one powers the
        # best-effort ai_suggestion enrichment pass (see agents/suggestions.py),
        # not a whole category's analysis, so a missing key/network failure
        # here should never affect accessibility/SEO scoring.
        self._gemini_client = gemini_client or GeminiClient()
        self._jobs: dict[str, ReportJob] = {}

    def create_job(self, url: str) -> str:
        """Registers a new job and kicks off its background run. Returns the job id."""
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = ReportJob(
            id=job_id,
            url=url,
            status=AuditStatus.PENDING,
            progress={step: "pending" for step in _STEPS},
        )
        asyncio.create_task(self._run(job_id, url))
        return job_id

    def get_job(self, job_id: str) -> Optional[ReportJob]:
        return self._jobs.get(job_id)

    async def _run(self, job_id: str, url: str) -> None:
        job = self._jobs[job_id]
        job.status = AuditStatus.RUNNING
        job.progress["scrape"] = "running"
        job_started = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        logger.info("job.start job_id=%s url=%s", job_id, url)

        scrape_started = time.perf_counter()
        try:
            page_data = await self._scrape_fn(url)
        except ScraperError as exc:
            job.progress["scrape"] = "failed"
            job.status = AuditStatus.FAILED
            job.error = str(exc)
            logger.warning(
                "job.failed job_id=%s url=%s stage=scrape duration=%.2fs error=%s",
                job_id, url, time.perf_counter() - scrape_started, exc,
            )
            return
        except Exception as exc:  # noqa: BLE001 - guard against unexpected scrape failures
            job.progress["scrape"] = "failed"
            job.status = AuditStatus.FAILED
            job.error = f"Unexpected error scraping '{url}': {exc}"
            logger.warning(
                "job.failed job_id=%s url=%s stage=scrape duration=%.2fs error=%s",
                job_id, url, time.perf_counter() - scrape_started, exc,
            )
            return

        job.progress["scrape"] = "completed"
        logger.info(
            "job.step_done job_id=%s step=scrape duration=%.2fs", job_id, time.perf_counter() - scrape_started
        )
        context = {"page_data": page_data}

        async def tracked(step: str, coro: Awaitable[CategoryResult]) -> tuple[str, CategoryResult]:
            job.progress[step] = "running"
            result = await coro
            # run_agent_safely() marks a real agent failure with this exact
            # summary prefix; a legitimate result with score=None (e.g. Gemini
            # omitting the optional `score` field) should still read "completed".
            failed = bool(result.summary) and result.summary.startswith("Analysis failed:")
            job.progress[step] = "failed" if failed else "completed"
            return step, result

        async def tracked_visual() -> tuple[CategoryResult, Optional[PageScreenshots]]:
            job.progress["visual"] = "running"
            result, screenshots = await self._run_visual_safely(url)
            failed = bool(result.summary) and result.summary.startswith("Analysis failed:")
            job.progress["visual"] = "failed" if failed else "completed"
            return result, screenshots

        accessibility_outcome, seo_outcome, copy_outcome, performance_outcome, (visual, screenshots) = (
            await asyncio.gather(
                tracked("accessibility", run_agent_safely(self._accessibility_agent, url, context)),
                tracked("seo", run_agent_safely(self._seo_agent, url, context)),
                tracked("copy", run_agent_safely(self._copy_agent, url, context)),
                tracked("performance", run_agent_safely(self._performance_agent, url, {})),
                tracked_visual(),
            )
        )
        outcomes = dict([accessibility_outcome, seo_outcome, copy_outcome, performance_outcome])

        try:
            outcomes["accessibility"], outcomes["seo"] = await enrich_with_ai_suggestions(
                page_data, outcomes["accessibility"], outcomes["seo"], self._gemini_client
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is a bonus, never a reason to fail the job
            logger.warning("job.suggestion_enrichment_failed job_id=%s url=%s error=%s", job_id, url, exc)

        audit_result = AuditResult(
            accessibility=outcomes["accessibility"], seo=outcomes["seo"], copy=outcomes["copy"]
        )
        job.result = combine_report(audit_result, outcomes["performance"], visual, screenshots)
        job.result.run_context = _build_run_context(
            url, started_at, page_data, outcomes["performance"]
        )
        job.status = AuditStatus.COMPLETED
        logger.info(
            "job.done job_id=%s url=%s duration=%.2fs overall_score=%s progress=%s",
            job_id, url, time.perf_counter() - job_started, job.result.summary.overall_score, job.progress,
        )

    async def _run_visual_safely(self, url: str) -> tuple[CategoryResult, Optional[PageScreenshots]]:
        """Capture screenshots, then run VisualAgent — each stage isolated on its own.

        A capture failure (e.g. Playwright unavailable) or a VisualAgent
        failure (e.g. Gemini unreachable) each yield a score=None
        CategoryResult rather than failing the whole job.
        """
        try:
            screenshots = await self._screenshot_fn(url)
        except Exception as exc:  # noqa: BLE001 - guard against unexpected capture failures
            return (
                CategoryResult(
                    category=AuditCategory.VISUAL,
                    score=None,
                    score_status=ScoreStatus.NOT_RUN,
                    summary=f"Analysis failed: {exc}",
                    recommendations=[],
                    raw_data=None,
                ),
                None,
            )

        # Same rule as report.py's builder: a render we can't verify is not
        # evidence, and a visual assessment written from a blank capture would
        # contradict the very screenshot printed beside it.
        if screenshots.quality is not None and screenshots.quality.is_degraded:
            logger.info(
                "job.visual_skipped url=%s reason=degraded_render detail=%s",
                url, screenshots.quality.reason,
            )
            return insufficient_evidence_result(screenshots.quality), screenshots

        result = await run_agent_safely(self._visual_agent, url, {"screenshots": screenshots})
        return result, screenshots
