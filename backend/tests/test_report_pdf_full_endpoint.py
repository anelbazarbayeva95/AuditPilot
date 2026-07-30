"""Tests for POST /report/pdf/full — the PDF export path for today's job-based
StructuredAuditReport shape (see pdf_report.build_pdf_report_from_structured)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import main
from models.schemas import AuditCategory, CategoryResult, ReportSummary, StructuredAuditReport


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def make_report_payload() -> dict:
    report = StructuredAuditReport(
        summary=ReportSummary(
            overall_score=86.0,
            category_scores={
                "accessibility": 90.0,
                "seo": 85.0,
                "performance": 80.0,
                "copy": 88.0,
                "visual": 87.0,
            },
            issue_counts={"medium": 2},
        ),
        accessibility=CategoryResult(category=AuditCategory.ACCESSIBILITY, score=90.0, recommendations=[]),
        seo=CategoryResult(category=AuditCategory.SEO, score=85.0, recommendations=[]),
        performance=CategoryResult(category=AuditCategory.PERFORMANCE, score=80.0, recommendations=[]),
        copy=CategoryResult(category=AuditCategory.COPY, score=88.0, recommendations=[]),
        visual=CategoryResult(category=AuditCategory.VISUAL, score=87.0, recommendations=[]),
        recommendations=[],
    )
    return {"url": "https://example.com", "report": report.model_dump(mode="json")}


def test_report_pdf_full_returns_pdf(client):
    response = client.post("/report/pdf/full", json=make_report_payload())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_report_pdf_full_malformed_body_returns_422(client):
    response = client.post("/report/pdf/full", json={"url": "https://example.com"})
    assert response.status_code == 422


def test_report_pdf_full_includes_screenshot(client):
    payload = make_report_payload()
    # A 1x1 transparent PNG, base64-encoded — just needs to decode as a valid image.
    payload["report"]["screenshot_viewport_base64"] = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    response = client.post("/report/pdf/full", json=payload)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
