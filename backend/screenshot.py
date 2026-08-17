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
from models.schemas import ScreenshotQuality
from render_quality import analyze_render_quality

DEFAULT_TIMEOUT_MS = 30_000
VIEWPORT_WIDTH = DESKTOP_VIEWPORT["width"]
VIEWPORT_HEIGHT = DESKTOP_VIEWPORT["height"]

# How long to let late work (lazy-loaded media, webfonts, deferred hydration)
# settle after `load` fires but before the shutter. Without this the capture
# routinely wins the race against the page's own hero content.
SETTLE_MS = 1_200
NETWORK_IDLE_MS = 8_000

logger = logging.getLogger(__name__)


class ScreenshotError(Exception):
    """Raised when a page cannot be reached, loaded, or screenshotted."""


@dataclass
class PageScreenshots:
    """PNG bytes for the same page load, captured two ways.

    `quality` is the measured usability of the viewport capture — see
    render_quality.py. It's optional so older callers and test fixtures that
    build this by hand keep working; None means "not measured", which the
    report discloses rather than assuming a good render.
    """

    full_page_png: bytes
    viewport_png: bytes
    quality: ScreenshotQuality | None = None


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

            await _settle_page(page)

            try:
                viewport_png = await page.screenshot(full_page=False)
                full_page_png = await page.screenshot(full_page=True)
            except PlaywrightError as exc:
                raise ScreenshotError(f"Failed to capture screenshot of '{url}': {exc}") from exc

            quality = analyze_render_quality(viewport_png)

            # One retry, because the common cause is a race rather than a
            # broken page: give the slow work more room and shoot again. If the
            # second attempt is no better, the degraded verdict stands and gets
            # disclosed downstream instead of quietly passing as evidence.
            if quality.is_degraded:
                logger.info("screenshot.retry url=%s reason=%s", url, quality.reason)
                try:
                    await _settle_page(page, settle_ms=SETTLE_MS * 3)
                    retry_viewport_png = await page.screenshot(full_page=False)
                    retry_quality = analyze_render_quality(retry_viewport_png)
                    if not retry_quality.is_degraded:
                        viewport_png = retry_viewport_png
                        full_page_png = await page.screenshot(full_page=True)
                    quality = retry_quality
                except PlaywrightError as exc:
                    logger.warning("screenshot.retry_failed url=%s error=%s", url, exc)

            duration = time.perf_counter() - started
            logger.info(
                "screenshot.done url=%s duration=%.2fs viewport_bytes=%d full_page_bytes=%d quality=%s",
                url, duration, len(viewport_png), len(full_page_png), quality.status,
            )
            return PageScreenshots(
                full_page_png=full_page_png, viewport_png=viewport_png, quality=quality
            )
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


async def _settle_page(page, settle_ms: int = SETTLE_MS) -> None:
    """Give the page every chance to finish rendering before the shutter.

    Three separate things routinely finish *after* `load` on a real marketing
    page, and each one alone is enough to produce a blank hero: in-flight
    requests, unresolved webfonts, and media that only loads once it scrolls
    into view. So: wait out the network, wait for fonts, scroll the whole page
    to trigger lazy loading, return to the top, and let it settle.

    Every step is best-effort — a page that never goes network-idle (analytics
    beacons, open sockets) is normal, and none of this is worth failing a
    capture over.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_MS)
    except Exception:  # noqa: BLE001 - a chatty page never goes idle; not an error
        pass

    try:
        await page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) {
                    try { await document.fonts.ready; } catch (err) { /* ignore */ }
                }
                const step = Math.max(200, window.innerHeight);
                for (let y = 0; y < document.body.scrollHeight; y += step) {
                    window.scrollTo(0, y);
                    await new Promise((r) => setTimeout(r, 60));
                }
                window.scrollTo(0, 0);
                await new Promise((r) => setTimeout(r, 120));
            }"""
        )
    except Exception as exc:  # noqa: BLE001 - CSP or a hostile page can block this
        logger.debug("screenshot.settle_script_skipped error=%s", exc)

    try:
        await page.wait_for_timeout(settle_ms)
    except Exception:  # noqa: BLE001
        pass
