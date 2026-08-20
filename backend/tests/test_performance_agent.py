"""Unit tests for PerformanceAgent (Milestone 7). No real Lighthouse/Chrome needed."""

from __future__ import annotations

import pytest

from agents.performance import PerformanceAgent, PerformanceAgentError
from lighthouse_runner import LighthouseError, LighthouseRun
from models.schemas import (
    AuditCategory,
    PerformanceCheck,
    PerformanceMetrics,
    PerformanceRunConfig,
)


def good_metrics(**overrides) -> PerformanceMetrics:
    defaults = dict(performance_score=95.0, lcp_ms=1800.0, cls=0.05, inp_ms=150.0)
    defaults.update(overrides)
    return PerformanceMetrics(**defaults)


@pytest.fixture
def agent() -> PerformanceAgent:
    return PerformanceAgent()


def test_good_metrics_no_findings(agent):
    result = agent.run_checks(good_metrics())
    assert result.findings == []
    assert result.score == 95.0


@pytest.mark.parametrize("score,expected_severity", [(85, "medium"), (30, "high")])
def test_low_performance_score_flagged(agent, score, expected_severity):
    result = agent.run_checks(good_metrics(performance_score=score))
    matches = [f for f in result.findings if f.check == PerformanceCheck.LOW_PERFORMANCE_SCORE]
    assert len(matches) == 1
    assert matches[0].severity == expected_severity


@pytest.mark.parametrize("lcp,expected_severity", [(3000, "medium"), (5000, "high")])
def test_slow_lcp_flagged(agent, lcp, expected_severity):
    result = agent.run_checks(good_metrics(lcp_ms=lcp))
    matches = [f for f in result.findings if f.check == PerformanceCheck.SLOW_LCP]
    assert len(matches) == 1
    assert matches[0].severity == expected_severity


def test_high_cls_flagged(agent):
    result = agent.run_checks(good_metrics(cls=0.3))
    assert any(f.check == PerformanceCheck.HIGH_CLS and f.severity == "high" for f in result.findings)


def test_slow_inp_flagged(agent):
    result = agent.run_checks(good_metrics(inp_ms=600))
    assert any(f.check == PerformanceCheck.SLOW_INP and f.severity == "high" for f in result.findings)


def test_missing_metrics_not_flagged(agent):
    result = agent.run_checks(PerformanceMetrics())
    assert result.findings == []
    assert result.score is None


class TestAnalyzePerformance:
    async def test_propagates_lighthouse_error(self, agent, monkeypatch):
        async def fake_run_lighthouse(url):
            raise LighthouseError("chrome not found")

        monkeypatch.setattr("agents.performance.run_lighthouse", fake_run_lighthouse)
        with pytest.raises(PerformanceAgentError, match="Lighthouse failed"):
            await agent.analyze_performance("https://example.com")

    async def test_analyze_wraps_into_category_result(self, agent, monkeypatch):
        async def fake_run_lighthouse(url):
            return LighthouseRun(
                metrics=good_metrics(lcp_ms=5000),
                run_config=PerformanceRunConfig(form_factor="desktop"),
                opportunities=[],
            )

        monkeypatch.setattr("agents.performance.run_lighthouse", fake_run_lighthouse)
        category_result = await agent.analyze("https://example.com", {})

        assert category_result.category == AuditCategory.PERFORMANCE
        assert len(category_result.recommendations) == 1
        assert category_result.raw_data["metrics"]["lcp_ms"] == 5000
