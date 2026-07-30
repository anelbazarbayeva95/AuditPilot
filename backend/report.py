"""Milestone 9: combine all agents' outputs into one structured audit report.

Kept decoupled from AuditOrchestrator/AuditResult (which only cover
Accessibility/SEO/Copy — see orchestrator.py) rather than changing their
shape: ReportBuilder runs AuditOrchestrator, PerformanceAgent, and (Milestone
11) screenshot capture + VisualAgent all in parallel and merges the results.
A PerformanceAgent or VisualAgent failure (Lighthouse/Chrome/Gemini
unavailable) is isolated the same way AuditOrchestrator isolates its agents.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Awaitable, Callable, Optional

from agents.performance import PerformanceAgent
from agents.visual import VisualAgent
from models.schemas import (
    AuditCategory,
    AuditResult,
    CategoryResult,
    Recommendation,
    ReportSummary,
    StructuredAuditReport,
)
from orchestrator import AuditOrchestrator
from screenshot import PageScreenshots, ScreenshotError, capture_screenshots

ScreenshotFn = Callable[[str], Awaitable[PageScreenshots]]

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Runs the 3-agent orchestrator, PerformanceAgent, and VisualAgent in parallel, then combines them."""

    def __init__(
        self,
        orchestrator: Optional[AuditOrchestrator] = None,
        performance_agent: Optional[PerformanceAgent] = None,
        visual_agent: Optional[VisualAgent] = None,
        screenshot_fn: Optional[ScreenshotFn] = None,
    ) -> None:
        self._orchestrator = orchestrator or AuditOrchestrator()
        self._performance_agent = performance_agent or PerformanceAgent()
        self._visual_agent = visual_agent or VisualAgent()
        self._screenshot_fn = screenshot_fn or capture_screenshots

    async def build(self, url: str) -> StructuredAuditReport:
        """Raises ScraperError if the page can't be scraped at all (nothing to analyze)."""
        started = time.perf_counter()
        audit_result, performance, (visual, screenshots) = await asyncio.gather(
            self._orchestrator.run(url),
            self._run_performance_safely(url),
            self._run_visual_safely(url),
        )
        report = combine_report(audit_result, performance, visual, screenshots)
        logger.info(
            "report.build done url=%s duration=%.2fs overall_score=%s "
            "category_scores=%s",
            url, time.perf_counter() - started, report.summary.overall_score, report.summary.category_scores,
        )
        return report

    async def _run_performance_safely(self, url: str) -> CategoryResult:
        started = time.perf_counter()
        logger.info("performance_agent.start url=%s", url)
        try:
            result = await self._performance_agent.analyze(url, {})
        except Exception as exc:  # noqa: BLE001 - isolate like AuditOrchestrator does
            logger.warning(
                "performance_agent.failed url=%s duration=%.2fs error=%s",
                url, time.perf_counter() - started, exc,
            )
            return _failed_category(AuditCategory.PERFORMANCE, exc)
        logger.info(
            "performance_agent.done url=%s duration=%.2fs score=%s",
            url, time.perf_counter() - started, result.score,
        )
        return result

    async def _run_visual_safely(self, url: str) -> tuple[CategoryResult, Optional[PageScreenshots]]:
        """Captures screenshots, then runs VisualAgent against them.

        Both the capture step and the Gemini call are isolated: a
        screenshot-capture failure (e.g. Playwright unavailable) or a
        VisualAgent failure (e.g. Gemini unreachable) each produce a
        score=None CategoryResult rather than failing the whole report.
        """
        started = time.perf_counter()
        try:
            screenshots = await self._screenshot_fn(url)
        except ScreenshotError as exc:
            logger.warning(
                "visual_agent.failed url=%s duration=%.2fs stage=screenshot error=%s",
                url, time.perf_counter() - started, exc,
            )
            return _failed_category(AuditCategory.VISUAL, exc), None
        except Exception as exc:  # noqa: BLE001 - guard against unexpected capture failures
            logger.warning(
                "visual_agent.failed url=%s duration=%.2fs stage=screenshot error=%s",
                url, time.perf_counter() - started, exc,
            )
            return _failed_category(AuditCategory.VISUAL, exc), None

        try:
            result = await self._visual_agent.analyze(url, {"screenshots": screenshots})
        except Exception as exc:  # noqa: BLE001 - isolate like AuditOrchestrator does
            logger.warning(
                "visual_agent.failed url=%s duration=%.2fs stage=analyze error=%s",
                url, time.perf_counter() - started, exc,
            )
            result = _failed_category(AuditCategory.VISUAL, exc)
        else:
            logger.info(
                "visual_agent.done url=%s duration=%.2fs score=%s",
                url, time.perf_counter() - started, result.score,
            )
        return result, screenshots


def _failed_category(category: AuditCategory, exc: Exception) -> CategoryResult:
    return CategoryResult(
        category=category, score=None, summary=f"Analysis failed: {exc}", recommendations=[], raw_data=None
    )


def combine_report(
    audit_result: AuditResult,
    performance: CategoryResult,
    visual: Optional[CategoryResult] = None,
    screenshots: Optional[PageScreenshots] = None,
) -> StructuredAuditReport:
    """Pure combining logic — unit testable without running any agent.

    `visual`/`screenshots` default to "not run" so existing 2-arg callers
    (pre-Milestone 11) keep working.
    """
    visual = visual or CategoryResult(
        category=AuditCategory.VISUAL, score=None, summary="Not run", recommendations=[], raw_data=None
    )

    category_scores = {
        "accessibility": audit_result.accessibility.score,
        "seo": audit_result.seo.score,
        "performance": performance.score,
        "copy": audit_result.copy.score,
        "visual": visual.score,
    }
    overall_score = _average(list(category_scores.values()))

    recommendations: list[Recommendation] = [
        *audit_result.accessibility.recommendations,
        *audit_result.seo.recommendations,
        *performance.recommendations,
        *audit_result.copy.recommendations,
        *visual.recommendations,
    ]
    recommendations.sort(key=lambda r: _SEVERITY_RANK.get(r.severity.value, 99))

    issue_counts: dict[str, int] = {}
    for rec in recommendations:
        issue_counts[rec.severity.value] = issue_counts.get(rec.severity.value, 0) + 1

    unavailable = [category for category, score in category_scores.items() if score is None]
    if unavailable:
        logger.info("report.combine categories_unavailable=%s", unavailable)

    return StructuredAuditReport(
        summary=ReportSummary(
            overall_score=overall_score,
            category_scores=category_scores,
            issue_counts=issue_counts,
        ),
        accessibility=audit_result.accessibility,
        seo=audit_result.seo,
        performance=performance,
        copy=audit_result.copy,
        visual=visual,
        recommendations=recommendations,
        screenshot_full_page_base64=_b64(screenshots.full_page_png) if screenshots else None,
        screenshot_viewport_base64=_b64(screenshots.viewport_png) if screenshots else None,
    )


def _average(scores: list[Optional[float]]) -> Optional[float]:
    available = [s for s in scores if s is not None]
    return sum(available) / len(available) if available else None


def _b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
