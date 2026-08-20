"""Runs Lighthouse CLI against a URL and extracts Core Web Vitals."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional

from models.schemas import PerformanceMetrics, PerformanceOpportunity, PerformanceRunConfig

LIGHTHOUSE_TIMEOUT_S = 90

# Lighthouse's CLI default is mobile emulation with simulated 4G throttling.
# The rest of this pipeline — scraper.py and screenshot.py — renders a desktop
# 1280x900 viewport, so inheriting that default meant publishing a
# mobile-throttled score beside a desktop screenshot with nothing saying so.
# The two now agree, and whichever profile is used is recorded and printed.
LIGHTHOUSE_PRESET = "desktop"

# Lighthouse audits whose `details.items` name real resources with real costs.
# These are what turn "audit render-blocking resources" into a fix with a
# filename, a size, and an expected saving attached.
_OPPORTUNITY_AUDIT_IDS = (
    "render-blocking-resources",
    "unused-javascript",
    "unused-css-rules",
    "uses-responsive-images",
    "uses-optimized-images",
    "server-response-time",
    "unminified-javascript",
    "unminified-css",
    "uses-text-compression",
    "legacy-javascript",
)

_MAX_OPPORTUNITIES = 6
_MAX_RESOURCES_PER_OPPORTUNITY = 3

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

_CHROME_EXECUTABLE_NAMES = ("chrome", "chrome.exe", "Chromium", "headless_shell")


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
            else:
                path = _find_installed_chromium(candidate)
    except Exception as exc:  # noqa: BLE001 - this is a best-effort fallback only
        logger.debug("lighthouse.chrome_path_fallback unavailable error=%s", exc)

    if path is None:
        logger.warning(
            "lighthouse.chrome_path_fallback_failed — no usable Chromium executable found; "
            "Performance audits will fail until CHROME_PATH is set or `playwright install "
            "chromium` has been run with a browser build matching the installed `playwright` "
            "package version."
        )

    _playwright_chrome_path_cache["path"] = path
    return path


def _find_installed_chromium(expected_candidate: Optional[str]) -> Optional[str]:
    """Best-effort fallback for when Playwright's *exact expected* browser
    revision path doesn't exist — e.g. the `playwright` pip package was
    upgraded without re-running `playwright install chromium`, so the
    revision baked into the package no longer matches what's on disk.
    Rather than giving up, glob for any installed Chromium build under the
    same browsers root (PLAYWRIGHT_BROWSERS_PATH, or the parent of the
    expected path) and use whichever is found first.
    """
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not root and expected_candidate:
        # Layout is <root>/chromium-<rev>/<platform-specific-nested-path>/
        # <executable> — nesting depth varies by OS (e.g. macOS's
        # chromium-<rev>/chrome-mac/Chromium.app/Contents/MacOS/Chromium is
        # deeper than Linux's chromium-<rev>/chrome-linux/chrome), so walk up
        # from the candidate until we find the chromium-<rev> ancestor
        # itself, rather than assuming a fixed number of path segments.
        node = os.path.dirname(expected_candidate)
        while node and node != os.path.dirname(node):
            parent = os.path.dirname(node)
            if os.path.basename(node).startswith("chromium"):
                root = parent
                break
            node = parent
    if not root or not os.path.isdir(root):
        return None

    for name in _CHROME_EXECUTABLE_NAMES:
        pattern = os.path.join(root, "chromium*", "**", name)
        for match in sorted(glob.glob(pattern, recursive=True)):
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return match
    return None


@dataclass
class LighthouseRun:
    """Everything one Lighthouse run yields: the numbers, the conditions, the causes.

    The conditions travel with the metrics deliberately — a score separated
    from its form factor and throttling isn't reproducible, and an audit that
    can't be reproduced can't be checked.
    """

    metrics: PerformanceMetrics
    run_config: PerformanceRunConfig
    opportunities: list[PerformanceOpportunity]


async def run_lighthouse(url: str) -> LighthouseRun:
    started = time.perf_counter()
    logger.info("lighthouse.start url=%s", url)

    env = os.environ.copy()
    if not env.get("CHROME_PATH"):
        fallback_path = await _resolve_playwright_chrome_path()
        if fallback_path:
            logger.info("lighthouse.chrome_path_fallback path=%s", fallback_path)
            env["CHROME_PATH"] = fallback_path

    # Write the report to a file rather than reading it off stdout: `npx`
    # can print its own noise to stdout ahead of Lighthouse's JSON (a
    # first-run "need to install the following packages" banner, npm update
    # notices, etc.), which silently breaks a direct json.loads(stdout).
    # A file is immune to that regardless of what caused the noise.
    fd, output_path = tempfile.mkstemp(suffix=".json", prefix="lighthouse-")
    os.close(fd)

    cmd = [
        "npx", "--yes", "lighthouse", url,
        "--output=json", f"--output-path={output_path}", "--quiet",
        "--only-categories=performance",
        # Explicit, not inherited: see LIGHTHOUSE_PRESET above.
        f"--preset={LIGHTHOUSE_PRESET}",
        # --disable-dev-shm-usage: containerized/serverless hosts commonly
        # cap /dev/shm at 64MB, far below what Chrome's renderer wants for a
        # real-world page. Without this, the renderer can crash mid-load,
        # which Lighthouse's driver often surfaces as the misleading
        # CHROME_INTERSTITIAL_ERROR ("Chrome prevented page load with an
        # interstitial") rather than a clear crash message — this is the
        # standard fix for Lighthouse/Puppeteer/Chrome-in-Docker deployments.
        '--chrome-flags=--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage',
    ]
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=LIGHTHOUSE_TIMEOUT_S)
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
            with open(output_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("lighthouse.failed url=%s duration=%.2fs error=invalid_output: %s", url, duration, exc)
            raise LighthouseError(f"Lighthouse produced no valid report: {exc}") from exc
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass

    metrics = _parse_report(report)
    run_config = _parse_run_config(report)
    opportunities = _parse_opportunities(report)
    logger.info(
        "lighthouse.done url=%s duration=%.2fs performance_score=%s lcp_ms=%s cls=%s inp_ms=%s "
        "form_factor=%s opportunities=%d",
        url, duration, metrics.performance_score, metrics.lcp_ms, metrics.cls, metrics.inp_ms,
        run_config.form_factor, len(opportunities),
    )
    return LighthouseRun(metrics=metrics, run_config=run_config, opportunities=opportunities)


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
        fcp_ms=numeric("first-contentful-paint"),
        tbt_ms=numeric("total-blocking-time"),
        speed_index_ms=numeric("speed-index"),
    )


def _parse_run_config(report: dict[str, Any]) -> PerformanceRunConfig:
    """Read back the conditions Lighthouse actually ran under.

    Taken from the report rather than from the flags we passed, so the record
    stays honest if Lighthouse overrides or ignores something we asked for.
    """
    settings = report.get("configSettings") or {}
    environment = report.get("environment") or {}
    throttling = settings.get("throttling") or {}
    screen = settings.get("screenEmulation") or {}

    throttling_summary = None
    method = settings.get("throttlingMethod")
    if method == "provided":
        throttling_summary = "none (unthrottled, as provided by the host)"
    elif throttling:
        down_kbps = throttling.get("downloadThroughputKbps") or throttling.get("throughputKbps")
        cpu = throttling.get("cpuSlowdownMultiplier")
        pieces = []
        if method:
            pieces.append(str(method))
            if down_kbps:
                pieces.append(f"{down_kbps:g} kbps down")
            if cpu:
                pieces.append(f"{cpu:g}x CPU slowdown")
        throttling_summary = ", ".join(pieces) or None

    screen_summary = None
    if screen and not screen.get("disabled"):
        width, height = screen.get("width"), screen.get("height")
        ratio = screen.get("deviceScaleFactor")
        if width and height:
            screen_summary = f"{width}x{height}" + (f" @{ratio:g}x" if ratio else "")
    elif screen.get("disabled"):
        screen_summary = "disabled (host viewport)"

    return PerformanceRunConfig(
        lighthouse_version=report.get("lighthouseVersion"),
        form_factor=settings.get("formFactor"),
        screen_emulation=screen_summary,
        throttling=throttling_summary,
        runs=1,
        fetch_time=report.get("fetchTime"),
        final_url=report.get("finalDisplayedUrl") or report.get("finalUrl"),
        user_agent=environment.get("networkUserAgent") or report.get("userAgent"),
    )


def _parse_opportunities(report: dict[str, Any]) -> list[PerformanceOpportunity]:
    """Pull the named resources behind each performance opportunity.

    Lighthouse already knows which script is blocking the render and what
    deferring it would save; that detail is the difference between a
    recommendation and a homework assignment, so it comes through to the report
    rather than being flattened into generic advice.
    """
    audits = report.get("audits") or {}
    opportunities: list[PerformanceOpportunity] = []

    for audit_id in _OPPORTUNITY_AUDIT_IDS:
        audit = audits.get(audit_id)
        if not isinstance(audit, dict):
            continue
        # score == 1 means the audit passed; None means it didn't apply.
        if audit.get("score") in (1, None):
            continue

        details = audit.get("details") or {}
        items = details.get("items") or []
        savings_ms = details.get("overallSavingsMs")
        savings_bytes = details.get("overallSavingsBytes")
        if savings_ms is None and audit.get("numericValue") is not None:
            savings_ms = audit["numericValue"]

        resources = []
        for item in items[:_MAX_RESOURCES_PER_OPPORTUNITY]:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("source")
            if isinstance(url, dict):
                url = url.get("url")
            if url:
                resources.append(str(url))

        opportunities.append(
            PerformanceOpportunity(
                audit_id=audit_id,
                title=audit.get("title") or audit_id,
                savings_ms=float(savings_ms) if savings_ms is not None else None,
                savings_bytes=int(savings_bytes) if savings_bytes is not None else None,
                resources=resources,
            )
        )

    opportunities.sort(key=lambda o: (o.savings_ms or 0, o.savings_bytes or 0), reverse=True)
    return opportunities[:_MAX_OPPORTUNITIES]
