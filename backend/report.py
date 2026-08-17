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

from actions import build_action_plan
from agents.performance import PerformanceAgent
from agents.visual import VisualAgent, insufficient_evidence_result
from labels import humanize, round_half_up
from models.schemas import (
    AuditCategory,
    AuditResult,
    CategoryResult,
    Recommendation,
    ReportSummary,
    ScoreStatus,
    StructuredAuditReport,
)
from orchestrator import AuditOrchestrator
from screenshot import PageScreenshots, ScreenshotError, capture_screenshots

ScreenshotFn = Callable[[str], Awaitable[PageScreenshots]]

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# An equal-weight mean is transparent but says that a broken form label and a
# weak headline matter equally, which isn't true for either users or the
# business. These weights are declared here, renormalized over whichever
# categories actually produced a score, and printed in the report — the point
# isn't that they're the only defensible split, it's that they're visible and
# arguable instead of implicit.
CATEGORY_WEIGHTS: dict[str, float] = {
    "accessibility": 0.25,
    "performance": 0.25,
    "seo": 0.20,
    "copy": 0.15,
    "visual": 0.15,
}

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

        # A capture that came back mostly blank can't support a visual
        # assessment, and assessing it anyway is how a report ends up praising
        # a hero section that isn't in its own screenshot. Refuse the judgment
        # rather than make one up.
        if screenshots.quality is not None and screenshots.quality.is_degraded:
            logger.info(
                "visual_agent.skipped url=%s reason=degraded_render detail=%s",
                url, screenshots.quality.reason,
            )
            return insufficient_evidence_result(screenshots.quality), screenshots

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
        category=category,
        score=None,
        score_status=ScoreStatus.NOT_RUN,
        summary=f"Analysis failed: {exc}",
        recommendations=[],
        raw_data=None,
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
        category=AuditCategory.VISUAL,
        score=None,
        score_status=ScoreStatus.NOT_RUN,
        summary="Not run",
        recommendations=[],
        raw_data=None,
    )

    categories = {
        "accessibility": audit_result.accessibility,
        "seo": audit_result.seo,
        "performance": performance,
        "copy": audit_result.copy,
        "visual": visual,
    }
    category_scores = {name: result.score for name, result in categories.items()}
    overall_score, weights, excluded, explanation = _weighted_overall(categories)

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

    if excluded:
        logger.info("report.combine categories_excluded=%s", excluded)

    action_plan, kpi_notes = build_action_plan(categories)

    return StructuredAuditReport(
        summary=ReportSummary(
            overall_score=overall_score,
            category_scores=category_scores,
            issue_counts=issue_counts,
            weights=weights,
            excluded_categories=excluded,
            score_explanation=explanation,
        ),
        accessibility=audit_result.accessibility,
        seo=audit_result.seo,
        performance=performance,
        copy=audit_result.copy,
        visual=visual,
        recommendations=recommendations,
        action_plan=action_plan,
        kpi_notes=kpi_notes,
        screenshot_full_page_base64=_b64(screenshots.full_page_png) if screenshots else None,
        screenshot_viewport_base64=_b64(screenshots.viewport_png) if screenshots else None,
        screenshot_quality=screenshots.quality if screenshots else None,
    )


def _weighted_overall(
    categories: dict[str, CategoryResult],
) -> tuple[Optional[float], dict[str, float], dict[str, str], Optional[str]]:
    """Weighted overall score, plus the weights, the exclusions, and the arithmetic.

    A category with no score is dropped from the calculation and the weights
    renormalize over what's left — but the drop is *recorded* rather than
    silently absorbed. Averaging four categories and presenting the result as
    an audit of five is the quiet version of overstating coverage.
    """
    included: dict[str, float] = {}
    excluded: dict[str, str] = {}

    for name, result in categories.items():
        if result.score is not None and result.score_status is ScoreStatus.SCORED:
            included[name] = CATEGORY_WEIGHTS.get(name, 0.0)
        elif result.score_status is ScoreStatus.INSUFFICIENT_EVIDENCE:
            excluded[name] = "insufficient evidence"
        elif result.summary and result.summary.startswith("Analysis failed:"):
            excluded[name] = "analysis failed"
        else:
            excluded[name] = "not run"

    total_weight = sum(included.values())
    if not included or total_weight <= 0:
        return None, {}, excluded, "No category produced a score, so no overall score is reported."

    normalized = {name: weight / total_weight for name, weight in included.items()}
    overall = sum(categories[name].score * weight for name, weight in normalized.items())

    # The printed arithmetic has to reproduce the printed answer. Rounding the
    # weights to whole percents doesn't: 29% + 24% + 29% + 18% of those scores
    # sums to 61.7, not the 61.3 actually computed, so a reader checking the
    # maths finds it doesn't add up — in a report whose whole argument is that
    # its numbers are checkable. Weights are shown to one decimal, each
    # contribution is shown, and the total is stated before rounding.
    parts = [
        f"{humanize(name)} {round_half_up(categories[name].score):g} x {weight * 100:.1f}% "
        f"({categories[name].score * weight:.1f})"
        for name, weight in normalized.items()
    ]
    explanation = (
        f"Weighted average: {' + '.join(parts)} = {overall:.1f}, "
        f"reported as {round_half_up(overall):g}/100."
    )
    if excluded:
        excluded_text = ", ".join(f"{humanize(name)} ({why})" for name, why in excluded.items())
        explanation += f" Excluded: {excluded_text}. Weights renormalized over the rest."

    return round(overall, 1), normalized, excluded, explanation


def _b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
