"""Runs Lighthouse CLI against a URL and extracts Core Web Vitals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from models.schemas import PerformanceMetrics

LIGHTHOUSE_TIMEOUT_S = 90

logger = logging.getLogger(__name__)


class LighthouseError(Exception):
    """Raised when Lighthouse can't run or its output can't be parsed."""


# Lighthouse's chrome-launcher only auto-detects a *separately installed*
# system Chrome/Chromium, or an explicit CHROME_PATH env var — it has no
# knowledge of Playwright's own bundled Chromium, even though Playwright is
# already a project dependency and, on a fresh checkout, is often the only
# Chromium binary actually present. Without this fallback, run_lighthouse()
# fails immediately with "The CHROME_PATH environment variable must be set"
# on any machine that never separately installed system Chrome — this was
# the confirmed break point in the Performance pipeline. We only fill this
# in when the caller hasn't already set CHROME_PATH themselves, so existing
# setups that rely on a system Chrome install are unaffected.
_playwright_chrome_path_cache: dict[str, Optional[str]] = {}


async def _resolve_playwright_chrome_path() -> Optional[str]:
    if "path" in _playwright_chrome_path_cache:
        return _playwright_chrome_path_cache["path"]

    path: Optional[str] = None
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            candidate = pw.chromium.executable_path
            if candidate and os.path.exists(candidate):
                path = candidate
    except Exception as exc:  # noqa: BLE001 - this is a best-effort fallback only
        logger.debug("lighthouse.chrome_path_fallback unavailable error=%s", exc)

    _playwright_chrome_path_cache["path"] = path
    return path


async def run_lighthouse(url: str) -> PerformanceMetrics:
    started = time.perf_counter()
    logger.info("lighthouse.start url=%s", url)

    env = os.environ.copy()
    if not env.get("CHROME_PATH"):
        fallback_path = await _resolve_playwright_chrome_path()
        if fallback_path:
            logger.info("lighthouse.chrome_path_fallback path=%s", fallback_path)
            env["CHROME_PATH"] = fallback_path

    cmd = [
        "npx", "--yes", "lighthouse", url,
        "--output=json", "--quiet",
        "--only-categories=performance",
        '--chrome-flags=--headless=new --no-sandbox --disable-gpu',
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=LIGHTHOUSE_TIMEOUT_S)
    except asyncio.TimeoutError as exc:
        duration = time.perf_counter() - started
        logger.warning("lighthouse.failed url=%s duration=%.2fs error=timeout", url, duration)
        raise LighthouseError(f"Lighthouse timed out auditing '{url}'") from exc
    except OSError as exc:
        duration = time.perf_counter() - started
        logger.warning("lighthouse.failed url=%s duration=%.2fs error=%s", url, duration, exc)
        raise LighthouseError(f"Failed to launch Lighthouse: {exc}") from exc

    duration = time.perf_counter() - started

    if proc.returncode != 0:
        logger.warning(
            "lighthouse.failed url=%s duration=%.2fs returncode=%s stderr=%s",
            url, duration, proc.returncode, stderr.decode()[:500],
        )
        raise LighthouseError(f"Lighthouse exited {proc.returncode}: {stderr.decode()[:500]}")

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.warning("lighthouse.failed url=%s duration=%.2fs error=invalid_json: %s", url, duration, exc)
        raise LighthouseError(f"Lighthouse returned invalid JSON: {exc}") from exc

    metrics = _parse_report(report)
    logger.info(
        "lighthouse.done url=%s duration=%.2fs performance_score=%s lcp_ms=%s cls=%s inp_ms=%s",
        url, duration, metrics.performance_score, metrics.lcp_ms, metrics.cls, metrics.inp_ms,
    )
    return metrics


def _parse_report(report: dict[str, Any]) -> PerformanceMetrics:
    try:
        audits = report["audits"]
        perf_score = report["categories"]["performance"]["score"]
    except KeyError as exc:
        raise LighthouseError(f"Lighthouse report missing expected field: {exc}") from exc

    def numeric(audit_id: str) -> float | None:
        value = audits.get(audit_id, {}).get("numericValue")
        return float(value) if value is not None else None

    inp = numeric("interaction-to-next-paint") or numeric("experimental-interaction-to-next-paint")

    return PerformanceMetrics(
        performance_score=round(perf_score * 100, 1) if perf_score is not None else None,
        lcp_ms=numeric("largest-contentful-paint"),
        cls=numeric("cumulative-layout-shift"),
        inp_ms=inp,
    )
