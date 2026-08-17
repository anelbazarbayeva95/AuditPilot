"""Tests for Milestone 9 report combining (report.py), + Milestone 11 visual/screenshot wiring."""

from __future__ import annotations

import base64

import pytest

from agents.visual import insufficient_evidence_result
from labels import round_half_up
from models.schemas import (
    AuditCategory,
    AuditResult,
    CategoryResult,
    Recommendation,
    ScoreStatus,
    ScreenshotQuality,
    Severity,
)
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
    # Weighted, not a flat mean: accessibility/performance 25% each, SEO 20%,
    # copy/visual 15% each (see report.CATEGORY_WEIGHTS).
    expected = 90 * 0.25 + 70 * 0.25 + 80 * 0.20 + 85 * 0.15 + 60 * 0.15
    assert report.summary.overall_score == pytest.approx(expected, abs=0.05)
    assert report.summary.weights == pytest.approx(
        {"accessibility": 0.25, "seo": 0.20, "performance": 0.25, "copy": 0.15, "visual": 0.15}
    )
    assert report.summary.excluded_categories == {}
    assert report.summary.score_explanation is not None
    assert len(report.recommendations) == 5


def test_recommendations_sorted_by_severity():
    report = combine_report(make_audit_result(), make_performance(), make_visual())
    severities = [r.severity for r in report.recommendations]
    assert severities == [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def test_issue_counts_by_severity():
    report = combine_report(make_audit_result(), make_performance(), make_visual())
    assert report.summary.issue_counts == {"critical": 1, "high": 1, "medium": 1, "low": 1, "info": 1}


def test_overall_score_excludes_failed_performance_and_says_so():
    report = combine_report(make_audit_result(), make_performance(score=None), make_visual())
    assert report.summary.category_scores["performance"] is None

    # Performance drops out and the remaining weights renormalize over 0.75.
    expected = (90 * 0.25 + 80 * 0.20 + 85 * 0.15 + 60 * 0.15) / 0.75
    assert report.summary.overall_score == pytest.approx(expected, abs=0.05)

    # The exclusion is recorded rather than silently absorbed — an audit of
    # four categories must not present itself as an audit of five.
    assert "performance" in report.summary.excluded_categories
    assert "performance" not in report.summary.weights
    assert "Excluded" in report.summary.score_explanation


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


# ---------------------------------------------------------------------------
# Degraded renders and insufficient evidence
# ---------------------------------------------------------------------------

def degraded_quality() -> ScreenshotQuality:
    return ScreenshotQuality(
        status="degraded", dominant_color_pct=71.3, uniform_row_pct=64.3, content_top_pct=82.0,
        reason="The page did not finish rendering before capture: 71% of the image is a single flat color.",
    )


class TestDegradedScreenshot:
    async def test_visual_agent_is_not_run_on_a_degraded_render(self):
        """The failure this exists to prevent: judging a page from a blank capture."""
        calls = []

        class SpyVisualAgent:
            category = AuditCategory.VISUAL

            async def analyze(self, url, context):
                calls.append(url)
                raise AssertionError("VisualAgent must not run on a degraded capture")

        async def fake_screenshots(url):
            return PageScreenshots(
                full_page_png=b"full", viewport_png=b"viewport", quality=degraded_quality()
            )

        builder = ReportBuilder(
            orchestrator=_FakeOrchestrator(),
            performance_agent=_FakePerformanceAgent(),
            visual_agent=SpyVisualAgent(),
            screenshot_fn=fake_screenshots,
        )
        report = await builder.build("https://example.com")

        assert calls == []
        assert report.visual.score is None
        assert report.visual.score_status is ScoreStatus.INSUFFICIENT_EVIDENCE

    async def test_degraded_render_is_disclosed_not_hidden(self):
        async def fake_screenshots(url):
            return PageScreenshots(
                full_page_png=b"full", viewport_png=b"viewport", quality=degraded_quality()
            )

        builder = ReportBuilder(
            orchestrator=_FakeOrchestrator(),
            performance_agent=_FakePerformanceAgent(),
            screenshot_fn=fake_screenshots,
        )
        report = await builder.build("https://example.com")

        assert report.screenshot_quality is not None
        assert report.screenshot_quality.is_degraded
        # The screenshot is still carried — as documentation of the failed
        # capture, which the PDF labels as such.
        assert report.screenshot_viewport_base64 is not None
        assert "did not finish rendering" in report.visual.summary

    def test_insufficient_evidence_is_excluded_from_the_overall_score(self):
        visual = insufficient_evidence_result(degraded_quality())
        report = combine_report(make_audit_result(), make_performance(), visual)

        assert report.summary.excluded_categories["visual"] == "insufficient evidence"
        assert "visual" not in report.summary.weights
        # Weights renormalize over the four categories that did produce a score.
        expected = (90 * 0.25 + 70 * 0.25 + 80 * 0.20 + 85 * 0.15) / 0.85
        assert report.summary.overall_score == pytest.approx(expected, abs=0.05)


class _FakeOrchestrator:
    async def run(self, url):
        return make_audit_result()


class _FakePerformanceAgent:
    async def analyze(self, url, context):
        return make_performance()


class TestScoreArithmeticIsCheckable:
    def test_printed_terms_reproduce_the_printed_total(self):
        """A reader who checks the maths must get the number that's printed.

        Rounding the weights to whole percents broke this: the terms summed to
        61.7 while the report said 61.
        """
        import re

        report = combine_report(make_audit_result(), make_performance(), make_visual())
        explanation = report.summary.score_explanation

        terms = [float(t) for t in re.findall(r"\((\d+\.\d)\)", explanation)]
        assert len(terms) == 5, explanation
        # Each term is printed to one decimal, so the visible sum can drift by
        # up to half a tick per term — but not by the 0.4 that whole-percent
        # weights introduced.
        assert sum(terms) == pytest.approx(report.summary.overall_score, abs=0.3)

    def test_reported_score_uses_conventional_rounding(self):
        assert round_half_up(61.5) == 62
        assert round_half_up(62.5) == 63  # not Python's round-half-even 62
        assert round_half_up(61.4) == 61

    def test_explanation_states_the_rounded_figure(self):
        report = combine_report(make_audit_result(), make_performance(), make_visual())

        assert "reported as" in report.summary.score_explanation


class TestActionPlanConsolidation:
    def test_one_fix_across_two_categories_is_one_action(self):
        audit = make_audit_result()
        audit.accessibility.recommendations = [Recommendation(
            title="Missing alt text", description="No alt attribute.", severity=Severity.HIGH,
            category=AuditCategory.ACCESSIBILITY, rule_id="missing_alt_text",
        )]
        audit.seo.recommendations = [Recommendation(
            title="Missing image alt text", description="No alt text.", severity=Severity.LOW,
            category=AuditCategory.SEO, rule_id="missing_image_alt_text",
        )]

        report = combine_report(audit, make_performance(), make_visual())
        alt_actions = [a for a in report.action_plan if a.key == "alt-text"]

        assert len(alt_actions) == 1
        assert alt_actions[0].findings_resolved == 2
        assert set(alt_actions[0].categories) == {"accessibility", "seo"}
        assert alt_actions[0].primary_standard.startswith("WCAG 1.1.1")

    def test_merging_keeps_the_more_severe_characterization(self):
        audit = make_audit_result()
        audit.accessibility.recommendations = [Recommendation(
            title="Missing alt text", description="d", severity=Severity.HIGH,
            category=AuditCategory.ACCESSIBILITY, rule_id="missing_alt_text",
        )]
        audit.seo.recommendations = [Recommendation(
            title="Missing image alt text", description="d", severity=Severity.LOW,
            category=AuditCategory.SEO, rule_id="missing_image_alt_text",
        )]

        report = combine_report(audit, make_performance(), make_visual())
        action = next(a for a in report.action_plan if a.key == "alt-text")

        assert action.severity is Severity.HIGH  # never quietly downgraded

    def test_lighthouse_score_becomes_a_kpi_note(self):
        performance = CategoryResult(
            category=AuditCategory.PERFORMANCE, score=25.0,
            recommendations=[Recommendation(
                title="Low Lighthouse performance score", description="25/100.",
                severity=Severity.HIGH, category=AuditCategory.PERFORMANCE,
                rule_id="low_performance_score",
            )],
        )
        report = combine_report(make_audit_result(), performance, make_visual())

        assert not [a for a in report.action_plan if "low_performance_score" in a.rule_ids]
        assert report.kpi_notes
        assert "not a task in itself" in report.kpi_notes[0]

    def test_performance_opportunities_become_concrete_actions(self):
        performance = CategoryResult(
            category=AuditCategory.PERFORMANCE, score=25.0,
            raw_data={"opportunities": [{
                "audit_id": "render-blocking-resources",
                "title": "Eliminate render-blocking resources",
                "savings_ms": 1240.0, "savings_bytes": 98304,
                "resources": ["https://example.com/main.css"],
            }]},
        )
        report = combine_report(make_audit_result(), performance, make_visual())
        action = next(a for a in report.action_plan if a.key == "perf-render-blocking-resources")

        assert "main.css" in action.description
        assert action.estimated_saving is not None
        assert "1,240 ms" in action.estimated_saving
