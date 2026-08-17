"""
Unit tests for the FastAPI routes in main.py.

`/audit` (scraping) and `/audit/full` (multi-agent) both depend on Playwright
and/or Gemini reaching the network, so these tests monkeypatch the module-
level scraper/orchestrator hooks with fakes — no browser or API key needed.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import main
from models.schemas import AuditCategory, AuditResult, CategoryResult, ScrapedPageData
from scraper import ScraperError


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


class TestCors:
    def test_allowed_origin_gets_cors_header(self, client):
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_disallowed_origin_gets_no_cors_header(self, client):
        response = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers

    def test_credentials_not_allowed(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-credentials" not in response.headers


class TestAuditScrapeEndpoint:
    def test_malformed_url_returns_422(self, client):
        response = client.post("/audit", json={"url": "not-a-url"})
        assert response.status_code == 422

    def test_scrape_success(self, client, monkeypatch):
        page = ScrapedPageData(url="https://example.com", title="Example")

        async def fake_scrape(url: str) -> ScrapedPageData:
            return page

        monkeypatch.setattr(main, "scrape_website", fake_scrape)
        response = client.post("/audit", json={"url": "https://example.com"})

        assert response.status_code == 200
        assert response.json()["title"] == "Example"

    def test_scrape_failure_returns_502(self, client, monkeypatch):
        async def fake_scrape(url: str) -> ScrapedPageData:
            raise ScraperError("could not load page")

        monkeypatch.setattr(main, "scrape_website", fake_scrape)
        response = client.post("/audit", json={"url": "https://example.com"})

        assert response.status_code == 502
        assert "could not load page" in response.json()["detail"]


class _FakeOrchestrator:
    def __init__(self, result: AuditResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.last_url: str | None = None

    async def run(self, url: str) -> AuditResult:
        self.last_url = url
        if self._error is not None:
            raise self._error
        return self._result


def make_audit_result() -> AuditResult:
    return AuditResult(
        overall_score=85.0,
        accessibility=CategoryResult(category=AuditCategory.ACCESSIBILITY, score=90.0),
        seo=CategoryResult(category=AuditCategory.SEO, score=85.0),
        copy=CategoryResult(category=AuditCategory.COPY, score=80.0),
    )


class TestAuditFullEndpoint:
    def test_malformed_url_returns_422(self, client):
        response = client.post("/audit/full", json={"url": "not-a-url"})
        assert response.status_code == 422

    def test_full_audit_success(self, client, monkeypatch):
        fake_orchestrator = _FakeOrchestrator(result=make_audit_result())
        monkeypatch.setattr(main, "_orchestrator", fake_orchestrator)

        response = client.post("/audit/full", json={"url": "https://example.com"})

        assert response.status_code == 200
        body = response.json()
        assert body["overall_score"] == 85.0
        assert body["accessibility"]["score"] == 90.0
        assert body["seo"]["score"] == 85.0
        assert body["copy"]["score"] == 80.0
        # Pydantic's HttpUrl normalizes a bare domain to include a trailing slash.
        assert fake_orchestrator.last_url == "https://example.com/"

    def test_scrape_failure_returns_502(self, client, monkeypatch):
        fake_orchestrator = _FakeOrchestrator(error=ScraperError("could not load page"))
        monkeypatch.setattr(main, "_orchestrator", fake_orchestrator)

        response = client.post("/audit/full", json={"url": "https://example.com"})

        assert response.status_code == 502
        assert "could not load page" in response.json()["detail"]

    def test_unexpected_error_returns_500(self, client, monkeypatch):
        fake_orchestrator = _FakeOrchestrator(error=RuntimeError("boom"))
        monkeypatch.setattr(main, "_orchestrator", fake_orchestrator)

        response = client.post("/audit/full", json={"url": "https://example.com"})

        assert response.status_code == 500
        assert "boom" in response.json()["detail"]
