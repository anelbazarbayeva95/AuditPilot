"""Performance agent (Milestone 7). Runs Lighthouse, checks Core Web Vitals thresholds."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.prioritization import prioritize
from labels import humanize, pluralize
from lighthouse_runner import LighthouseError, run_lighthouse
from models.schemas import (
    AuditCategory,
    CategoryCoverage,
    CategoryResult,
    ConfidenceLevel,
    CoverageMethod,
    DetectionMethod,
    Evidence,
    PerformanceCheck,
    PerformanceFinding,
    PerformanceMetrics,
    PerformanceOpportunity,
    PerformanceResult,
    PerformanceRunConfig,
    Recommendation,
    Severity,
)

# What a single automated Lighthouse run does and doesn't establish. Lab data
# under emulation is not what real users experience, and one run is a sample of
# one — both belong next to the score rather than in a footnote nobody reads.
PERFORMANCE_NOT_COVERED = [
    "Field data / real-user monitoring (CrUX)",
    "Run-to-run variance (this is a single run)",
    "Other pages, templates, and authenticated states",
    "Other devices, connection types, and geographies",
    "Back-end and API latency under load",
]

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
            score_explanation=_explain_score(result),
            coverage=coverage(),
            summary=_summarize(result),
            recommendations=[
                _finding_to_recommendation(f, result.opportunities) for f in result.findings
            ],
            raw_data=result.model_dump(),
        )

    async def analyze_performance(self, url: str) -> PerformanceResult:
        try:
            run = await run_lighthouse(url)
        except LighthouseError as exc:
            raise PerformanceAgentError(f"Lighthouse failed: {exc}") from exc
        return self.run_checks(run.metrics, run.run_config, run.opportunities)

    def run_checks(
        self,
        metrics: PerformanceMetrics,
        run_config: PerformanceRunConfig | None = None,
        opportunities: list[PerformanceOpportunity] | None = None,
    ) -> PerformanceResult:
        findings: list[PerformanceFinding] = []
        findings.extend(self._check_performance_score(metrics))
        findings.extend(self._check_lcp(metrics))
        findings.extend(self._check_cls(metrics))
        findings.extend(self._check_inp(metrics))
        return PerformanceResult(
            score=metrics.performance_score,
            findings=findings,
            metrics=metrics,
            run_config=run_config,
            opportunities=opportunities or [],
        )

    @staticmethod
    def _check_performance_score(m: PerformanceMetrics) -> list[PerformanceFinding]:
        if m.performance_score is None or m.performance_score >= 90:
            return []
        severity = Severity.HIGH if m.performance_score < 50 else Severity.MEDIUM
        return [PerformanceFinding(
            check=PerformanceCheck.LOW_PERFORMANCE_SCORE, severity=severity,
            message=f"Lighthouse performance score is {m.performance_score:.0f}/100.",
            measured_value=f"{m.performance_score:.0f}/100",
            threshold="good is >= 90/100",
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
            measured_value=f"{m.lcp_ms:.0f} ms",
            threshold=f"good is <= {LCP_GOOD_MS} ms",
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
            measured_value=f"{m.cls:.2f}",
            threshold=f"good is <= {CLS_GOOD}",
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
            measured_value=f"{m.inp_ms:.0f} ms",
            threshold=f"good is <= {INP_GOOD_MS} ms",
        )]


class PerformanceAgentError(Exception):
    """Raised when Lighthouse can't be run."""


_RECOMMENDATION_TEXT = {
    PerformanceCheck.LOW_PERFORMANCE_SCORE: "Work through the opportunities Lighthouse identified, largest saving first.",
    PerformanceCheck.SLOW_LCP: "Optimize the largest above-the-fold element: compress/preload images, remove render-blocking CSS/JS.",
    PerformanceCheck.HIGH_CLS: "Reserve space for images/ads/embeds and avoid injecting content above existing content.",
    PerformanceCheck.SLOW_INP: "Break up long JavaScript tasks and reduce main-thread work during interactions.",
}

# Which Lighthouse opportunities are worth naming under which finding. Anything
# else stays in the Performance section's own opportunity table rather than
# being attached to a metric it may not be causing.
_OPPORTUNITIES_BY_CHECK: dict[PerformanceCheck, tuple[str, ...]] = {
    PerformanceCheck.SLOW_LCP: (
        "render-blocking-resources", "server-response-time", "uses-responsive-images",
        "uses-optimized-images", "uses-text-compression",
    ),
    PerformanceCheck.SLOW_INP: ("unused-javascript", "legacy-javascript", "unminified-javascript"),
    PerformanceCheck.LOW_PERFORMANCE_SCORE: (
        "render-blocking-resources", "unused-javascript", "unused-css-rules",
        "server-response-time", "uses-responsive-images", "uses-optimized-images",
        "unminified-javascript", "unminified-css", "uses-text-compression", "legacy-javascript",
    ),
}


def _describe_opportunity(opportunity: PerformanceOpportunity) -> str:
    """'Eliminate render-blocking resources: main.css, app.js (~320 ms, 48 KB)'.

    Everything in the string is measured — the resource names, the saving, and
    the size all come straight out of the Lighthouse audit.
    """
    parts = []
    if opportunity.savings_ms:
        parts.append(f"~{opportunity.savings_ms:.0f} ms")
    if opportunity.savings_bytes:
        parts.append(f"{opportunity.savings_bytes / 1024:.0f} KB")
    saving = f" ({', '.join(parts)})" if parts else ""

    if opportunity.resources:
        named = ", ".join(_shorten_resource(r) for r in opportunity.resources)
        return f"{opportunity.title}: {named}{saving}"
    return f"{opportunity.title}{saving}"


def _shorten_resource(url: str) -> str:
    """Filename plus host — a full CDN URL is unreadable in a sentence."""
    without_query = url.split("?", 1)[0]
    filename = without_query.rstrip("/").rsplit("/", 1)[-1]
    return filename or without_query


def _finding_to_recommendation(
    finding: PerformanceFinding,
    opportunities: list[PerformanceOpportunity] | None = None,
) -> Recommendation:
    """Turn a threshold breach into a fix that names the resources behind it.

    "Audit render-blocking resources, bundle size, and server response time" is
    a task list for whoever reads it, not a recommendation. Lighthouse already
    knows which files are responsible and what deferring them would save, so
    when that detail exists it goes in the recommendation itself.
    """
    description = _RECOMMENDATION_TEXT.get(finding.check, finding.message)

    relevant_ids = _OPPORTUNITIES_BY_CHECK.get(finding.check, ())
    relevant = [o for o in (opportunities or []) if o.audit_id in relevant_ids][:3]
    if relevant:
        detail = "; ".join(_describe_opportunity(o) for o in relevant)
        description = f"{description} Measured on this page — {detail}."

    return prioritize(
        Recommendation(
            title=humanize(finding.check),
            description=description,
            severity=finding.severity,
            category=AuditCategory.PERFORMANCE,
            context=finding.context,
            rule_id=finding.check.value,
            detection=DetectionMethod.AUTOMATED,
            confidence=ConfidenceLevel.HIGH,
            evidence=(
                Evidence(measured_value=finding.measured_value, threshold=finding.threshold)
                if finding.measured_value or finding.threshold
                else None
            ),
        )
    )


def coverage() -> CategoryCoverage:
    """What one lab run measures, and what it can't."""
    return CategoryCoverage(
        checks_run=[humanize(check) for check in PerformanceCheck],
        checks_not_covered=list(PERFORMANCE_NOT_COVERED),
        method=CoverageMethod.AUTOMATED,
        notes=(
            "A single Lighthouse lab run against one URL. The exact form factor, throttling, and "
            "Lighthouse version used are recorded in Methodology."
        ),
    )


def _explain_score(result: PerformanceResult) -> str:
    """Performance doesn't deduct from 100 — it reports Lighthouse's own score."""
    if result.metrics.performance_score is None:
        return "No performance score: Lighthouse did not return one."
    config = result.run_config
    conditions = ""
    if config and (config.form_factor or config.throttling):
        bits = [b for b in (config.form_factor, config.throttling) if b]
        conditions = f" measured under {', '.join(bits)}"
    return (
        f"Lighthouse performance score, reported as-is: "
        f"{result.metrics.performance_score:.0f}/100{conditions}. "
        "This category is not deduction-scored."
    )


def _summarize(result: PerformanceResult) -> str:
    if not result.findings:
        return "No Core Web Vitals issues detected in this run."
    return f"{pluralize(len(result.findings), 'performance issue')} found in this run."
