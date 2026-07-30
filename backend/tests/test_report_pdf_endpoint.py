"""Tests for POST /report/pdf (Milestone 8)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import main
from models.schemas import AuditCategory, AuditResult, CategoryResult


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def make_result_payload() -> dict:
    result = AuditResult(
        overall_score=88.0,
        accessibility=CategoryResult(category=AuditCategory.ACCESSIBILITY, score=90.0, recommendations=[]),
        seo=CategoryResult(category=AuditCategory.SEO, score=85.0, recommendations=[]),
        copy=CategoryResult(category=AuditCategory.COPY, score=90.0, recommendations=[]),
    )
    return {"url": "https://example.com", "result": result.model_dump(mode="json")}


def test_report_pdf_returns_pdf(client):
    response = client.post("/report/pdf", json=make_result_payload())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_report_pdf_malformed_body_returns_422(client):
    response = client.post("/report/pdf", json={"url": "https://example.com"})
    assert response.status_code == 422


def test_report_pdf_accepts_optional_visual_and_screenshot(client):
    payload = make_result_payload()
    payload["visual"] = CategoryResult(
        category=AuditCategory.VISUAL, score=70.0, recommendations=[]
    ).model_dump(mode="json")
    payload["screenshot_viewport_base64"] = None  # explicitly absent is fine

    response = client.post("/report/pdf", json=payload)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
