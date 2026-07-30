"""
Unit tests for AuditOrchestrator (Milestone 5).

Uses fake agents and a fake scrape function throughout — no real Playwright
browser or Gemini network access is needed. Covers: parallel execution with
correct shared context, overall_score averaging, per-agent failure
isolation, and scrape-failure propagation.
"""

from __future__ import annotations

import asyncio

import pytest

from models.schemas import AuditCategory, CategoryResult, ScrapedPageData
from orchestrator import AuditOrchestrator
from scraper import ScraperError


class FakeAgent:
    """Stand-in for a BaseAgent: records calls, returns a canned CategoryResult."""

    def __init__(self, category: AuditCategory, score: float | None = 90.0, error: Exception | None = None):
        self.category = category
        self._score = score
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def analyze(self, url: str, context: dict) -> CategoryResult:
        self.calls.append((url, context))
        if self._error is not None:
            raise self._error
        return CategoryResult(category=self.category, score=self._score, summary="ok")


class SlowFakeAgent(FakeAgent):
    """Adds an artificial delay so concurrency can be observed."""

    def __init__(self, *args, delay: float = 0.05, **kwargs):
        super().__init__(*args, **kwargs)
        self._delay = delay

    async def analyze(self, url: str, context: dict) -> CategoryResult:
        await asyncio.sleep(self._delay)
        return await super().analyze(url, context)


def make_page() -> ScrapedPageData:
    return ScrapedPageData(url="https://example.com", title="Example")


async def fake_scrape_ok(url: str) -> ScrapedPageData:
    return make_page()


async def fake_scrape_fails(url: str) -> ScrapedPageData:
    raise ScraperError(f"could not load {url}")


def make_orchestrator(accessibility_score=90.0, seo_score=80.0, copy_score=70.0, scrape_fn=fake_scrape_ok):
    return AuditOrchestrator(
        accessibility_agent=FakeAgent(AuditCategory.ACCESSIBILITY, score=accessibility_score),
        seo_agent=FakeAgent(AuditCategory.SEO, score=seo_score),
        copy_agent=FakeAgent(AuditCategory.COPY, score=copy_score),
        scrape_fn=scrape_fn,
    )


class TestHappyPath:
    async def test_returns_all_three_category_results(self):
        orchestrator = make_orchestrator()
        result = await orchestrator.run("https://example.com")

        assert result.accessibility.category == AuditCategory.ACCESSIBILITY
        assert result.seo.category == AuditCategory.SEO
        assert result.copy.category == AuditCategory.COPY

    async def test_overall_score_is_mean_of_the_three(self):
        orchestrator = make_orchestrator(accessibility_score=90.0, seo_score=80.0, copy_score=70.0)
        result = await orchestrator.run("https://example.com")
        assert result.overall_score == 80.0

    async def test_each_agent_receives_shared_page_data_context(self):
        accessibility_agent = FakeAgent(AuditCategory.ACCESSIBILITY)
        seo_agent = FakeAgent(AuditCategory.SEO)
        copy_agent = FakeAgent(AuditCategory.COPY)
        orchestrator = AuditOrchestrator(
            accessibility_agent=accessibility_agent,
            seo_agent=seo_agent,
            copy_agent=copy_agent,
            scrape_fn=fake_scrape_ok,
        )

        await orchestrator.run("https://example.com")

        for agent in (accessibility_agent, seo_agent, copy_agent):
            assert len(agent.calls) == 1
            called_url, called_context = agent.calls[0]
            assert called_url == "https://example.com"
            assert called_context["page_data"].url == "https://example.com"

    async def test_agents_run_concurrently_not_sequentially(self):
        # Three agents each sleeping 0.05s should take ~0.05s total if run in
        # parallel, not ~0.15s if run sequentially.
        orchestrator = AuditOrchestrator(
            accessibility_agent=SlowFakeAgent(AuditCategory.ACCESSIBILITY, delay=0.05),
            seo_agent=SlowFakeAgent(AuditCategory.SEO, delay=0.05),
            copy_agent=SlowFakeAgent(AuditCategory.COPY, delay=0.05),
            scrape_fn=fake_scrape_ok,
        )

        loop = asyncio.get_event_loop()
        start = loop.time()
        await orchestrator.run("https://example.com")
        elapsed = loop.time() - start

        assert elapsed < 0.12  # well under the 0.15s sequential-sum baseline


class TestAgentFailureIsolation:
    async def test_one_agent_failing_does_not_break_the_others(self):
        orchestrator = AuditOrchestrator(
            accessibility_agent=FakeAgent(AuditCategory.ACCESSIBILITY, score=95.0),
            seo_agent=FakeAgent(AuditCategory.SEO, score=85.0),
            copy_agent=FakeAgent(AuditCategory.COPY, error=RuntimeError("Gemini unreachable")),
            scrape_fn=fake_scrape_ok,
        )

        result = await orchestrator.run("https://example.com")

        assert result.accessibility.score == 95.0
        assert result.seo.score == 85.0
        assert result.copy.score is None
        assert "Gemini unreachable" in result.copy.summary

    async def test_overall_score_ignores_failed_agents(self):
        orchestrator = AuditOrchestrator(
            accessibility_agent=FakeAgent(AuditCategory.ACCESSIBILITY, score=90.0),
            seo_agent=FakeAgent(AuditCategory.SEO, score=70.0),
            copy_agent=FakeAgent(AuditCategory.COPY, error=RuntimeError("boom")),
            scrape_fn=fake_scrape_ok,
        )

        result = await orchestrator.run("https://example.com")
        assert result.overall_score == 80.0  # mean of 90 and 70 only

    async def test_overall_score_is_none_if_every_agent_fails(self):
        orchestrator = AuditOrchestrator(
            accessibility_agent=FakeAgent(AuditCategory.ACCESSIBILITY, error=RuntimeError("a")),
            seo_agent=FakeAgent(AuditCategory.SEO, error=RuntimeError("b")),
            copy_agent=FakeAgent(AuditCategory.COPY, error=RuntimeError("c")),
            scrape_fn=fake_scrape_ok,
        )

        result = await orchestrator.run("https://example.com")
        assert result.overall_score is None
        assert result.accessibility.score is None
        assert result.seo.score is None
        assert result.copy.score is None


class TestScrapeFailure:
    async def test_scrape_failure_propagates(self):
        orchestrator = make_orchestrator(scrape_fn=fake_scrape_fails)
        with pytest.raises(ScraperError):
            await orchestrator.run("https://example.com")
