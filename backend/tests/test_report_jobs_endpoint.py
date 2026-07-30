"""Tests for POST /report/jobs and GET /report/jobs/{id} (Milestone 10)."""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

import main
from jobs import JobManager
from models.schemas import AuditCategory, CategoryResult
from screenshot import PageScreenshots


class FakeAgent:
    def __init__(self, category: AuditCategory):
        self.category = category

    async def analyze(self, url, context):
        return CategoryResult(category=self.category, score=95.0, summary="ok")


async def fake_scrape(url: str):
    from models.schemas import ScrapedPageData
    return ScrapedPageData(url=url, title="Example")


async def fake_screenshot(url: str) -> PageScreenshots:
    return PageScreenshots(full_page_png=b"full-page-bytes", viewport_png=b"viewport-bytes")


@pytest.fixture
def client(monkeypatch) -> TestClient:
    fake_manager = JobManager(
        accessibility_agent=FakeAgent(AuditCategory.ACCESSIBILITY),
        seo_agent=FakeAgent(AuditCategory.SEO),
        copy_agent=FakeAgent(AuditCategory.COPY),
        performance_agent=FakeAgent(AuditCategory.PERFORMANCE),
        visual_agent=FakeAgent(AuditCategory.VISUAL),
        scrape_fn=fake_scrape,
        screenshot_fn=fake_screenshot,
    )
    monkeypatch.setattr(main, "_job_manager", fake_manager)
    return TestClient(main.app)


def test_create_and_poll_job_to_completion(client):
    create_response = client.post("/report/jobs", json={"url": "https://example.com"})
    assert create_response.status_code == 202
    job_id = create_response.json()["job_id"]

    async def poll():
        while True:
            response = client.get(f"/report/jobs/{job_id}")
            if response.json()["status"] in ("completed", "failed"):
                return response
            await asyncio.sleep(0.01)

    final = asyncio.run(asyncio.wait_for(poll(), timeout=2.0))
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "completed"
    assert body["result"]["summary"]["overall_score"] == 95.0


def test_unknown_job_id_returns_404(client):
    response = client.get("/report/jobs/does-not-exist")
    assert response.status_code == 404
