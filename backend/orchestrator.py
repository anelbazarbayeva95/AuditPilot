"""
AuditOrchestrator (Milestone 5 — multi-agent).

Scrapes a URL once, then runs AccessibilityAgent, SEOAgent, and CopyAgent
concurrently against the shared scraped data, and aggregates their
CategoryResults into a single AuditResult:

    {overall_score, accessibility, seo, copy}

Each agent is dependency-injectable (constructor args) so this class can be
unit tested with fakes — no real Playwright scrape or Gemini call required.

A single agent failing (e.g. CopyAgent when Gemini is unreachable) does not
fail the whole audit: that agent's slot gets a CategoryResult with
score=None and a summary describing the failure, while the other two
agents' real results still come back. Scraping itself is not isolated this
way — if the page can't be scraped at all, there's nothing for any agent to
analyze, so that failure propagates to the caller.

PerformanceAgent/Lighthouse are intentionally not wired in yet (still a
stub) — this milestone's scope is exactly Accessibility + SEO + Copy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from agents import AccessibilityAgent, CopyAgent, SEOAgent
from agents.base import BaseAgent
from models.schemas import AuditResult, CategoryResult, ScrapedPageData
from scraper import ScraperError, scrape_website

ScrapeFn = Callable[[str], Awaitable[ScrapedPageData]]

logger = logging.getLogger(__name__)


class AuditOrchestrator:
    """Runs Accessibility, SEO, and Copy agents in parallel and aggregates results."""

    def __init__(
        self,
        accessibility_agent: Optional[AccessibilityAgent] = None,
        seo_agent: Optional[SEOAgent] = None,
        copy_agent: Optional[CopyAgent] = None,
        scrape_fn: Optional[ScrapeFn] = None,
    ) -> None:
        self._accessibility_agent = accessibility_agent or AccessibilityAgent()
        self._seo_agent = seo_agent or SEOAgent()
        self._copy_agent = copy_agent or CopyAgent()
        self._scrape_fn = scrape_fn or scrape_website

    async def run(self, url: str) -> AuditResult:
        """Scrape `url`, run all three agents in parallel, and aggregate the results.

        Raises:
            ScraperError: if the page itself can't be scraped (nothing to analyze).
        """
        page_data = await self._scrape(url)
        context = {"page_data": page_data}

        accessibility_result, seo_result, copy_result = await asyncio.gather(
            run_agent_safely(self._accessibility_agent, url, context),
            run_agent_safely(self._seo_agent, url, context),
            run_agent_safely(self._copy_agent, url, context),
        )

        overall_score = _average_score(
            [accessibility_result.score, seo_result.score, copy_result.score]
        )

        return AuditResult(
            overall_score=overall_score,
            accessibility=accessibility_result,
            seo=seo_result,
            copy=copy_result,
        )

    async def _scrape(self, url: str) -> ScrapedPageData:
        """Render and scrape the target page. Propagates ScraperError as-is."""
        try:
            return await self._scrape_fn(url)
        except ScraperError:
            raise


def _average_score(scores: list[Optional[float]]) -> Optional[float]:
    """Mean of the non-None scores, or None if every agent failed to produce one."""
    available = [s for s in scores if s is not None]
    if not available:
        return None
    return sum(available) / len(available)


async def run_agent_safely(agent: BaseAgent, url: str, context: dict) -> CategoryResult:
    """Run one agent, isolating its failure so it can't take down the whole audit.

    Module-level (not just an AuditOrchestrator method) so other runners —
    e.g. jobs.py's per-agent progress tracking (Milestone 10) — can reuse the
    exact same isolation behavior.
    """
    category = agent.category.value
    started = time.perf_counter()
    logger.info("agent.start category=%s url=%s", category, url)

    try:
        result = await agent.analyze(url, context)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: isolate any agent failure
        duration = time.perf_counter() - started
        logger.warning(
            "agent.failed category=%s url=%s duration=%.2fs error=%s", category, url, duration, exc
        )
        return CategoryResult(
            category=agent.category,
            score=None,
            summary=f"Analysis failed: {exc}",
            recommendations=[],
            raw_data=None,
        )

    duration = time.perf_counter() - started
    logger.info(
        "agent.done category=%s url=%s duration=%.2fs score=%s recommendations=%d",
        category, url, duration, result.score, len(result.recommendations),
    )
    return result
