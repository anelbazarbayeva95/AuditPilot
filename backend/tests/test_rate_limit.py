"""Tests for per-client audit rate limiting (rate_limit.py)."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

import main
import rate_limit
from rate_limit import SlidingWindowLimiter, client_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit_then_reports_wait(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(2, 60, clock=clock)
        assert limiter.hit("a") is None
        clock.now += 10
        assert limiter.hit("a") is None
        clock.now += 10
        # Oldest event (t=1000) leaves the window at t=1060; it's now t=1020.
        assert limiter.hit("a") == pytest.approx(40)

    def test_window_slides(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 60, clock=clock)
        assert limiter.hit("a") is None
        clock.now += 61
        assert limiter.hit("a") is None

    def test_keys_are_independent(self):
        limiter = SlidingWindowLimiter(1, 60, clock=FakeClock())
        assert limiter.hit("a") is None
        assert limiter.hit("b") is None
        assert limiter.hit("a") is not None

    def test_refused_attempts_do_not_extend_the_wait(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 60, clock=clock)
        limiter.hit("a")
        for _ in range(5):
            limiter.hit("a")
        clock.now += 61
        assert limiter.hit("a") is None

    def test_stale_keys_are_swept(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 60, clock=clock)
        limiter.hit("one-off-visitor")
        clock.now += 61
        limiter.hit("someone-else")
        assert "one-off-visitor" not in limiter._events


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


class TestClientKey:
    def test_uses_socket_peer_by_default_and_ignores_the_header(self):
        assert client_key(_request("10.0.0.1", "203.0.113.9"), trusted_hops=0) == "10.0.0.1"

    def test_reads_the_entry_appended_by_the_trusted_proxy(self):
        # A client can prepend anything; only the right-most entry was written
        # by the one proxy we trust.
        request = _request("10.0.0.1", "1.2.3.4, 203.0.113.9")
        assert client_key(request, trusted_hops=1) == "203.0.113.9"

    def test_counts_hops_from_the_right(self):
        request = _request("10.0.0.1", "spoofed, 203.0.113.9, 10.0.0.2")
        assert client_key(request, trusted_hops=2) == "203.0.113.9"

    def test_falls_back_to_peer_when_header_is_short(self):
        assert client_key(_request("10.0.0.1"), trusted_hops=1) == "10.0.0.1"


def test_report_jobs_endpoint_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(rate_limit, "audit_limiter", SlidingWindowLimiter(1, 3600))

    class FakeManager:
        def create_job(self, url: str) -> str:
            return "job-1"

    monkeypatch.setattr(main, "_job_manager", FakeManager())
    client = TestClient(main.app)

    assert client.post("/report/jobs", json={"url": "https://example.com"}).status_code == 202
    refused = client.post("/report/jobs", json={"url": "https://example.com"})
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    assert "1 per hour" in refused.json()["detail"]


def test_report_jobs_endpoint_returns_503_when_queue_is_full(monkeypatch):
    from jobs import JobQueueFullError

    class FullManager:
        def create_job(self, url: str) -> str:
            raise JobQueueFullError("at capacity")

    monkeypatch.setattr(main, "_job_manager", FullManager())
    response = TestClient(main.app).post("/report/jobs", json={"url": "https://example.com"})
    assert response.status_code == 503
    assert response.json()["detail"] == "at capacity"
    assert "retry-after" in response.headers
