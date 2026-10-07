"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

import rate_limit


@pytest.fixture(autouse=True)
def _reset_audit_rate_limit():
    # The limiter is process-global (like the real deployment's), so without a
    # reset every endpoint test would spend from one shared allowance.
    rate_limit.audit_limiter._events.clear()
    yield
    rate_limit.audit_limiter._events.clear()
