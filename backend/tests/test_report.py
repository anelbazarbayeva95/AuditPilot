"""Tests for Milestone 9 report combining (report.py), + Milestone 11 visual/screenshot wiring."""

from __future__ import annotations

import base64

import pytest

from models.schemas import AuditCategory, AuditResult, CategoryResult, Recommendation, Severity
from report import ReportBuilder, combine_report
from screenshot import PageScreenshots


def rec(title: str, severity: Severity, category: AuditCategory) -> Recommendation:
    return Recommendation(title=title, description=f"{title} desc", severity=severity, category=category)


def make_audit_result() -> AuditResult:
    return AuditResult(
        overall_score=85.0,
        accessibility=CategoryResult(
            category=AuditCategory.ACCESSIBILITY, score=90.0,
            recommendations=[rec("A-high", Severity.HIGH, AuditCategory.ACCESSIBILITY)],
        ),
        seo=CategoryResult(
            category=AuditCategory.SEO, score=80.0,
            recommendations=[rec("S-low", Severity.LOW, AuditCategory.SEO)],
        ),
        copy=CategoryResult(
            category=AuditCategory.COPY, score=85.0,
            recommendations=[rec("C-critical", Severity.CRITICAL, AuditCategory.COPY)],
        ),
    )


def make_performance(score: float | None = 70.0) -> CategoryResult:
    return CategoryResult(
        category=AuditCategory.PERFORMANCE, score=score,
        recommendations=[rec("P-medium", Severity.MEDIUM, AuditCategory.PERFORMANCE)] if score is not None else [],
    )


def make_visual(score: float | None = 60.0) -> CategoryResult:
    return CategoryResult(
        category=AuditCategory.VISUAL, score=score,
        recommendations=[rec("V-info", Severity.INFO, AuditCategory.VISUAL)] if score is not None else [],
    )


def make_screenshots() -> PageScreenshots:
    return PageScreenshots(full_page_png=b"full-page-bytes", viewport_png=b"viewport-bytes")


def test_combine_report_shape():
    report = combine_report(make_audit_result(), make_performance(), make_visual())
    assert report.summary.category_scores == {
        "accessibility": 90.0, "seo": 80.0, "performance": 70.0, "copy": 85.0, "visual": 60.0,
    }
    assert report.summary.overall_score == pytest.approx(77.0)
    assert len(report.recommendations) == 5


def test_recommendations_sorted_by_severity():
    report = combine_report(make_audit_result(), make_performance(), make_visual())
    severities = [r.severity for r in report.recommendations]
    assert severities == [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def test_issue_counts_by_severity():
    report = combine_report(make_audit_result(), make_performance(), make_visual())
    assert report.summary.issue_counts == {"critical": 1, "high": 1, "medium": 1, "low": 1, "info": 1}


def test_overall_score_ignores_failed_performance():
    report = combine_report(make_audit_result(), make_performance(score=None), make_visual())
    assert report.summary.category_scores["performance"] is None
    assert report.summary.overall_score == pytest.approx((90.0 + 80.0 + 85.0 + 60.0) / 4)


def test_visual_defaults_to_not_run_when_omitted():
    """Pre-Milestone-11 callers that only pass (audit_result, performance) still work."""
    report = combine_report(make_audit_result(), make_performance())
    assert report.visual.score is None
    assert report.visual.summary == "Not run"
    assert report.summary.category_scores["visual"] is None
    assert report.screenshot_full_page_base64 is None
    assert report.screenshot_viewport_base64 is None


def test_screenshots_are_base64_encoded_onto_the_report():
    screenshots = make_screenshots()
    report = combine_report(make_audit_result(), make_performance(), make_visual(), screenshots)

    assert report.screenshot_full_page_base64 == base64.b64encode(b"full-page-bytes").decode("ascii")
    assert report.screenshot_viewport_base64 == base64.b64encode(b"viewport-bytes").decode("ascii")


class TestReportBuilder:
    async def test_build_runs_orchestrator_performance_and_visual_in_parallel(self):
        class FakeOrchestrator:
            async def run(self, url):
                return make_audit_result()

        class FakePerformanceAgent:
            async def analyze(self, url, context):
                return make_performance()

        class FakeVisualAgent:
            async def analyze(self, url, context):
                assert "screenshots" in context
                return make_visual()

        async def fake_screenshot_fn(url):
            return make_screenshots()

        builder = ReportBuilder(
            orchestrator=FakeOrchestrator(),
            performance_agent=FakePerformanceAgent(),
            visual_agent=FakeVisualAgent(),
            screenshot_fn=fake_screenshot_fn,
        )
        report = await builder.build("https://example.com")

        assert report.summary.overall_score is not None
        assert report.performance.score == 70.0
        assert report.visual.score == 60.0
        assert report.screenshot_full_page_base64 is not None

    async def test_performance_failure_is_isolated(self):
        class FakeOrchestrator:
            async def run(self, url):
                return make_audit_result()

        class FailingPerformanceAgent:
            async def analyze(self, url, context):
                raise RuntimeError("lighthouse unavailable")

        class FakeVisualAgent:
            async def analyze(self, url, context):
                return make_visual()

        async def fake_screenshot_fn(url):
            return make_screenshots()

        builder = ReportBuilder(
            orchestrator=FakeOrchestrator(),
            performance_agent=FailingPerformanceAgent(),
            visual_agent=FakeVisualAgent(),
            screenshot_fn=fake_screenshot_fn,
        )
        report = await builder.build("https://example.com")

        assert report.performance.score is None
        assert "lighthouse unavailable" in report.performance.summary
        assert report.summary.overall_score is not None  # still computed from the other agents

    async def test_screenshot_capture_failure_is_isolated(self):
        class FakeOrchestrator:
            async def run(self, url):
                return make_audit_result()

        class FakePerformanceAgent:
            async def analyze(self, url, context):
                return make_performance()

        class NeverCalledVisualAgent:
            async def analyze(self, url, context):
                raise AssertionError("VisualAgent should not run if screenshots failed to capture")

        async def failing_screenshot_fn(url):
            raise RuntimeError("no display available")

        builder = ReportBuilder(
            orchestrator=FakeOrchestrator(),
            performance_agent=FakePerformanceAgent(),
            visual_agent=NeverCalledVisualAgent(),
            screenshot_fn=failing_screenshot_fn,
        )
        report = await builder.build("https://example.com")

        assert report.visual.score is None
        assert "no display available" in report.visual.summary
        assert report.screenshot_full_page_base64 is None
        assert report.summary.overall_score is not None  # still computed from the other agents

    async def test_visual_agent_failure_is_isolated(self):
        class FakeOrchestrator:
            async def run(self, url):
                return make_audit_result()

        class FakePerformanceAgent:
            async def analyze(self, url, context):
                return make_performance()

        class FailingVisualAgent:
            async def analyze(self, url, context):
                raise RuntimeError("gemini vision down")

        async def fake_screenshot_fn(url):
            return make_screenshots()

        builder = ReportBuilder(
            orchestrator=FakeOrchestrator(),
            performance_agent=FakePerformanceAgent(),
            visual_agent=FailingVisualAgent(),
            screenshot_fn=fake_screenshot_fn,
        )
        report = await builder.build("https://example.com")

        assert report.visual.score is None
        assert "gemini vision down" in report.visual.summary
        # Screenshots were captured fine even though the Gemini call failed.
        assert report.screenshot_full_page_base64 is not None
