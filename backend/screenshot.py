"""
Screenshot capture (Milestone 11) via Playwright.

Captures two PNGs from a single page load: the full page (for layout/visual
hierarchy/contrast analysis) and just the viewport — "above the fold",
exactly what a visitor sees before scrolling (for CTA visibility analysis).
Kept standalone like scraper.py, so it can be exercised/tested independently
of VisualAgent and reused elsewhere if needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from browser_defaults import DESKTOP_LOCALE, DESKTOP_USER_AGENT, DESKTOP_VIEWPORT

DEFAULT_TIMEOUT_MS = 30_000
VIEWPORT_WIDTH = DESKTOP_VIEWPORT["width"]
VIEWPORT_HEIGHT = DESKTOP_VIEWPORT["height"]

logger = logging.getLogger(__name__)


class ScreenshotError(Exception):
    """Raised when a page cannot be reached, loaded, or screenshotted."""


@dataclass
class PageScreenshots:
    """PNG bytes for the same page load, captured two ways."""

    full_page_png: bytes
    viewport_png: bytes


async def capture_screenshots(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> PageScreenshots:
    """Render `url` in a headless browser and capture full-page + viewport screenshots.

    Args:
        url: Fully-qualified URL to screenshot (validated upstream via Pydantic HttpUrl).
        timeout_ms: Navigation timeout in milliseconds.

    Returns:
        A populated PageScreenshots instance.

    Raises:
        ScreenshotError: if the page cannot be reached, times out, returns an
            HTTP error status, or fails to capture for any other reason.
    """
    started = time.perf_counter()
    logger.info("screenshot.start url=%s", url)
    browser = None
    try:
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(headless=True)
            except PlaywrightError as exc:
                raise ScreenshotError(f"Failed to launch browser: {exc}") from exc

            # Same real desktop UA/locale/viewport as scraper.py — some sites
            # (e.g. dyson.com) 403 outright on Playwright's default headless
            # fingerprint. See browser_defaults.py.
            context = await browser.new_context(
                user_agent=DESKTOP_USER_AGENT,
                locale=DESKTOP_LOCALE,
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                response = await page.goto(url, wait_until="load", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise ScreenshotError(f"Timed out loading '{url}' after {timeout_ms}ms") from exc
            except PlaywrightError as exc:
                raise ScreenshotError(f"Failed to load '{url}': {exc}") from exc

            if response is not None and response.status >= 400:
                raise ScreenshotError(f"'{url}' responded with HTTP {response.status}")

            try:
                viewport_png = await page.screenshot(full_page=False)
                full_page_png = await page.screenshot(full_page=True)
            except PlaywrightError as exc:
                raise ScreenshotError(f"Failed to capture screenshot of '{url}': {exc}") from exc

            duration = time.perf_counter() - started
            logger.info(
                "screenshot.done url=%s duration=%.2fs viewport_bytes=%d full_page_bytes=%d",
                url, duration, len(viewport_png), len(full_page_png),
            )
            return PageScreenshots(full_page_png=full_page_png, viewport_png=viewport_png)
    except ScreenshotError as exc:
        logger.warning(
            "screenshot.failed url=%s duration=%.2fs error=%s", url, time.perf_counter() - started, exc
        )
        raise
    except Exception as exc:  # noqa: BLE001 - normalize any unexpected failure
        logger.warning(
            "screenshot.failed url=%s duration=%.2fs error=%s", url, time.perf_counter() - started, exc
        )
        raise ScreenshotError(f"Unexpected error capturing screenshots for '{url}': {exc}") from exc
    finally:
        if browser is not None:
            await browser.close()
