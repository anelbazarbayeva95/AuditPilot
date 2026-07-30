"""Performance agent (Milestone 7). Runs Lighthouse, checks Core Web Vitals thresholds."""

from __future__ import annotations

from typing import Any, Optional

from agents.base import BaseAgent
from lighthouse_runner import LighthouseError, run_lighthouse
from models.schemas import (
    AuditCategory,
    CategoryResult,
    PerformanceCheck,
    PerformanceFinding,
    PerformanceMetrics,
    PerformanceResult,
    Recommendation,
    Severity,
)

# https://web.dev/articles/vitals thresholds ("good" ceiling, "poor" floor).
LCP_GOOD_MS, LCP_POOR_MS = 2500, 4000
CLS_GOOD, CLS_POOR = 0.1, 0.25
INP_GOOD_MS, INP_POOR_MS = 200, 500


class PerformanceAgent(BaseAgent):
    category = AuditCategory.PERFORMANCE

    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        result = await self.analyze_performance(url)
        return CategoryResult(
            category=self.category,
            score=result.score,
            summary=_summarize(result),
            recommendations=[_finding_to_recommendation(f) for f in result.findings],
            raw_data=result.model_dump(),
        )

    async def analyze_performance(self, url: str) -> PerformanceResult:
        try:
            metrics = await run_lighthouse(url)
        except LighthouseError as exc:
            raise PerformanceAgentError(f"Lighthouse failed: {exc}") from exc
        return self.run_checks(metrics)

    def run_checks(self, metrics: PerformanceMetrics) -> PerformanceResult:
        findings: list[PerformanceFinding] = []
        findings.extend(self._check_performance_score(metrics))
        findings.extend(self._check_lcp(metrics))
        findings.extend(self._check_cls(metrics))
        findings.extend(self._check_inp(metrics))
        return PerformanceResult(score=metrics.performance_score, findings=findings, metrics=metrics)

    @staticmethod
    def _check_performance_score(m: PerformanceMetrics) -> list[PerformanceFinding]:
        if m.performance_score is None or m.performance_score >= 90:
            return []
        severity = Severity.HIGH if m.performance_score < 50 else Severity.MEDIUM
        return [PerformanceFinding(
            check=PerformanceCheck.LOW_PERFORMANCE_SCORE, severity=severity,
            message=f"Lighthouse performance score is {m.performance_score:.0f}/100.",
        )]

    @staticmethod
    def _check_lcp(m: PerformanceMetrics) -> list[PerformanceFinding]:
        if m.lcp_ms is None or m.lcp_ms <= LCP_GOOD_MS:
            return []
        severity = Severity.HIGH if m.lcp_ms > LCP_POOR_MS else Severity.MEDIUM
        return [PerformanceFinding(
            check=PerformanceCheck.SLOW_LCP, severity=severity,
            message=f"Largest Contentful Paint is {m.lcp_ms:.0f}ms (good is <= {LCP_GOOD_MS}ms).",
            context=f"{m.lcp_ms:.0f}ms",
        )]

    @staticmethod
    def _check_cls(m: PerformanceMetrics) -> list[PerformanceFinding]:
        if m.cls is None or m.cls <= CLS_GOOD:
            return []
        severity = Severity.HIGH if m.cls > CLS_POOR else Severity.MEDIUM
        return [PerformanceFinding(
            check=PerformanceCheck.HIGH_CLS, severity=severity,
            message=f"Cumulative Layout Shift is {m.cls:.2f} (good is <= {CLS_GOOD}).",
            context=f"{m.cls:.2f}",
        )]

    @staticmethod
    def _check_inp(m: PerformanceMetrics) -> list[PerformanceFinding]:
        if m.inp_ms is None or m.inp_ms <= INP_GOOD_MS:
            return []
        severity = Severity.HIGH if m.inp_ms > INP_POOR_MS else Severity.MEDIUM
        return [PerformanceFinding(
            check=PerformanceCheck.SLOW_INP, severity=severity,
            message=f"Interaction to Next Paint is {m.inp_ms:.0f}ms (good is <= {INP_GOOD_MS}ms).",
            context=f"{m.inp_ms:.0f}ms",
        )]


class PerformanceAgentError(Exception):
    """Raised when Lighthouse can't be run."""


_RECOMMENDATION_TEXT = {
    PerformanceCheck.LOW_PERFORMANCE_SCORE: "Audit render-blocking resources, bundle size, and server response time.",
    PerformanceCheck.SLOW_LCP: "Optimize the largest above-the-fold element: compress/preload images, remove render-blocking CSS/JS.",
    PerformanceCheck.HIGH_CLS: "Reserve space for images/ads/embeds and avoid injecting content above existing content.",
    PerformanceCheck.SLOW_INP: "Break up long JavaScript tasks and reduce main-thread work during interactions.",
}


def _finding_to_recommendation(finding: PerformanceFinding) -> Recommendation:
    return Recommendation(
        title=finding.check.value.replace("_", " ").title(),
        description=_RECOMMENDATION_TEXT.get(finding.check, finding.message),
        severity=finding.severity,
        category=AuditCategory.PERFORMANCE,
        context=finding.context,
    )


def _summarize(result: PerformanceResult) -> str:
    if not result.findings:
        return "No Core Web Vitals issues detected."
    return f"{len(result.findings)} performance issue(s) found."
