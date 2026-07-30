"""Tests for JobManager (Milestone 10, +visual step in Milestone 11). No network/Chrome/Gemini needed — all fakes."""

from __future__ import annotations

import asyncio

import pytest

from jobs import JobManager
from models.schemas import AuditCategory, AuditStatus, CategoryResult, ScrapedPageData
from scraper import ScraperError
from screenshot import PageScreenshots, ScreenshotError


class FakeAgent:
    def __init__(self, category: AuditCategory, score: float | None = 90.0, error: Exception | None = None, delay: float = 0.0):
        self.category = category
        self._score = score
        self._error = error
        self._delay = delay

    async def analyze(self, url: str, context: dict) -> CategoryResult:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return CategoryResult(category=self.category, score=self._score, summary="ok")


async def fake_scrape_ok(url: str) -> ScrapedPageData:
    return ScrapedPageData(url=url, title="Example")


async def fake_scrape_fails(url: str) -> ScrapedPageData:
    raise ScraperError(f"could not load {url}")


async def fake_screenshot_ok(url: str) -> PageScreenshots:
    return PageScreenshots(full_page_png=b"full-page-bytes", viewport_png=b"viewport-bytes")


async def fake_screenshot_fails(url: str) -> PageScreenshots:
    raise ScreenshotError(f"could not screenshot {url}")


def make_manager(**agent_kwargs) -> JobManager:
    return JobManager(
        accessibility_agent=agent_kwargs.get("accessibility") or FakeAgent(AuditCategory.ACCESSIBILITY),
        seo_agent=agent_kwargs.get("seo") or FakeAgent(AuditCategory.SEO),
        copy_agent=agent_kwargs.get("copy") or FakeAgent(AuditCategory.COPY),
        performance_agent=agent_kwargs.get("performance") or FakeAgent(AuditCategory.PERFORMANCE),
        visual_agent=agent_kwargs.get("visual") or FakeAgent(AuditCategory.VISUAL),
        scrape_fn=agent_kwargs.get("scrape_fn", fake_scrape_ok),
        screenshot_fn=agent_kwargs.get("screenshot_fn", fake_screenshot_ok),
    )


async def wait_for_completion(manager: JobManager, job_id: str, timeout: float = 2.0):
    async def poll():
        while True:
            job = manager.get_job(job_id)
            if job.status in (AuditStatus.COMPLETED, AuditStatus.FAILED):
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=timeout)


class TestJobLifecycle:
    async def test_unknown_job_returns_none(self):
        manager = make_manager()
        assert manager.get_job("does-not-exist") is None

    async def test_job_starts_pending_with_all_steps_pending(self):
        manager = make_manager()
        job_id = manager.create_job("https://example.com")
        job = manager.get_job(job_id)
        assert job.id == job_id
        assert job.status in (AuditStatus.PENDING, AuditStatus.RUNNING)
        assert set(job.progress) == {"scrape", "accessibility", "seo", "copy", "performance", "visual"}
        await wait_for_completion(manager, job_id)  # drain the background task before the loop closes

    async def test_job_completes_with_all_steps_completed(self):
        manager = make_manager()
        job_id = manager.create_job("https://example.com")
        job = await wait_for_completion(manager, job_id)

        assert job.status == AuditStatus.COMPLETED
        assert all(v == "completed" for v in job.progress.values())
        assert job.result is not None
        assert job.result.summary.overall_score == 90.0
        assert job.result.visual.score == 90.0
        assert job.result.screenshot_full_page_base64 is not None
        assert job.result.screenshot_viewport_base64 is not None

    async def test_scrape_failure_marks_job_failed(self):
        manager = make_manager(scrape_fn=fake_scrape_fails)
        job_id = manager.create_job("https://example.com")
        job = await wait_for_completion(manager, job_id)

        assert job.status == AuditStatus.FAILED
        assert job.progress["scrape"] == "failed"
        assert "could not load" in job.error
        # Agent steps never started.
        assert job.progress["accessibility"] == "pending"
        assert job.progress["visual"] == "pending"

    async def test_one_agent_failure_is_isolated(self):
        manager = make_manager(copy=FakeAgent(AuditCategory.COPY, error=RuntimeError("gemini down")))
        job_id = manager.create_job("https://example.com")
        job = await wait_for_completion(manager, job_id)

        assert job.status == AuditStatus.COMPLETED
        assert job.progress["copy"] == "failed"
        assert job.progress["accessibility"] == "completed"
        assert job.result.copy.score is None
        assert job.result.accessibility.score == 90.0

    async def test_visual_agent_failure_is_isolated(self):
        manager = make_manager(visual=FakeAgent(AuditCategory.VISUAL, error=RuntimeError("gemini vision down")))
        job_id = manager.create_job("https://example.com")
        job = await wait_for_completion(manager, job_id)

        assert job.status == AuditStatus.COMPLETED
        assert job.progress["visual"] == "failed"
        assert job.result.visual.score is None
        assert "gemini vision down" in job.result.visual.summary
        # Screenshots were captured fine even though the Gemini call failed.
        assert job.result.screenshot_full_page_base64 is not None
        # Other steps still completed normally.
        assert job.progress["accessibility"] == "completed"

    async def test_screenshot_capture_failure_is_isolated(self):
        manager = make_manager(screenshot_fn=fake_screenshot_fails)
        job_id = manager.create_job("https://example.com")
        job = await wait_for_completion(manager, job_id)

        assert job.status == AuditStatus.COMPLETED
        assert job.progress["visual"] == "failed"
        assert job.result.visual.score is None
        assert "could not screenshot" in job.result.visual.summary
        assert job.result.screenshot_full_page_base64 is None
        # Screenshot capture failing doesn't touch the other, independent steps.
        assert job.progress["accessibility"] == "completed"

    async def test_faster_agent_reports_progress_before_slower_one_finishes(self):
        manager = make_manager(
            accessibility=FakeAgent(AuditCategory.ACCESSIBILITY, delay=0.01),
            copy=FakeAgent(AuditCategory.COPY, delay=0.2),
        )
        job_id = manager.create_job("https://example.com")

        # Poll early: accessibility (fast) should complete well before copy (slow).
        await asyncio.sleep(0.08)
        job = manager.get_job(job_id)
        assert job.progress["accessibility"] == "completed"
        assert job.progress["copy"] in ("running", "pending")

        await wait_for_completion(manager, job_id)
