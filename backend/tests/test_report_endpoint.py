"""Tests for POST /report (Milestone 9)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import main
from models.schemas import AuditCategory, CategoryResult, ReportSummary, StructuredAuditReport


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


class FakeReportBuilder:
    async def build(self, url: str) -> StructuredAuditReport:
        empty = lambda cat: CategoryResult(category=cat, score=100.0, recommendations=[])
        return StructuredAuditReport(
            summary=ReportSummary(overall_score=100.0, category_scores={}, issue_counts={}),
            accessibility=empty(AuditCategory.ACCESSIBILITY),
            seo=empty(AuditCategory.SEO),
            performance=empty(AuditCategory.PERFORMANCE),
            copy=empty(AuditCategory.COPY),
            visual=empty(AuditCategory.VISUAL),
            recommendations=[],
        )


def test_report_endpoint_returns_combined_shape(client, monkeypatch):
    monkeypatch.setattr(main, "_report_builder", FakeReportBuilder())
    response = client.post("/report", json={"url": "https://example.com"})

    assert response.status_code == 200
    body = response.json()
    assert set(
        ["summary", "accessibility", "seo", "performance", "copy", "visual", "recommendations"]
    ) <= set(body.keys())
    assert body["summary"]["overall_score"] == 100.0


def test_report_endpoint_malformed_url_returns_422(client):
    response = client.post("/report", json={"url": "not-a-url"})
    assert response.status_code == 422
