"""
Website scraper (Milestone 1).

Uses Playwright (headless Chromium) to render a target URL and extract
structured page data: title, meta description, headings, images, buttons,
and links. This module is intentionally standalone (no Gemini, no agents)
so it can be exercised directly via POST /audit and later reused by the
orchestrator as shared context for the analysis agents.
"""

from __future__ import annotations

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from browser_defaults import DESKTOP_LOCALE, DESKTOP_USER_AGENT, DESKTOP_VIEWPORT
from egress_proxy import EgressProxy
from models.schemas import ButtonData, ImageData, InputData, LinkData, ScrapedPageData
from url_safety import UnsafeURLError, ensure_public_url

DEFAULT_TIMEOUT_MS = 30_000

_BUTTON_SELECTOR = "button, input[type='button'], input[type='submit'], [role='button']"
_INPUT_SELECTOR = (
    "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']), "
    "textarea, select"
)

# Attaches two small helpers to `window` before extraction: a real CSS
# selector computed from actual DOM structure (id if present, else a
# positional nth-of-type path up a few ancestors — never a guess, always
# derived from the live page), and the nearest real landmark ancestor
# (Header/Navigation/Footer/Main content). Defined once via page.evaluate()
# so every eval_on_selector_all() call below can reuse them instead of
# duplicating the logic per element type.
_ELEMENT_HELPERS_SCRIPT = """
() => {
    window.__auditpilot__ = {
        computeSelector(el) {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let node = el;
            let depth = 0;
            while (node && node.nodeType === 1 && depth < 4) {
                if (node.id) {
                    parts.unshift('#' + CSS.escape(node.id));
                    break;
                }
                let piece = node.tagName.toLowerCase();
                if (node.parentElement) {
                    const siblings = Array.from(node.parentElement.children).filter(
                        (sib) => sib.tagName === node.tagName
                    );
                    if (siblings.length > 1) {
                        piece += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                    }
                }
                parts.unshift(piece);
                node = node.parentElement;
                depth += 1;
            }
            return parts.join(' > ');
        },
        // innerText, not textContent: textContent concatenates every
        // descendant text node with no separator, so a heading split across
        // two spans comes back as one run-together word ("KYLIAN
        // MBAPPEMERCURIAL SUPERFLY"). innerText respects rendering, and the
        // whitespace collapse then flattens the line breaks it introduces.
        visibleText(el) {
            const raw = (el.innerText || el.textContent || '');
            return raw.replace(/\\s+/g, ' ').trim();
        },
        domExcerpt(el, limit = 220) {
            const html = (el.outerHTML || '').replace(/\\s+/g, ' ').trim();
            return html.length > limit ? html.slice(0, limit - 1) + '\\u2026' : html;
        },
        // Accessible name in the real precedence order the browser uses:
        // aria-labelledby > aria-label > content > value > title. The old
        // check only looked at content/value/aria-label, so a button named
        // solely by aria-labelledby or title was reported as nameless when it
        // isn't.
        accessibleName(el) {
            const labelledby = (el.getAttribute('aria-labelledby') || '').trim();
            if (labelledby) {
                const text = labelledby
                    .split(/\\s+/)
                    .map((id) => {
                        try {
                            const ref = document.getElementById(id);
                            return ref ? window.__auditpilot__.visibleText(ref) : '';
                        } catch (err) { return ''; }
                    })
                    .filter(Boolean)
                    .join(' ')
                    .trim();
                if (text) return {name: text, source: 'aria-labelledby'};
            }
            const ariaLabel = (el.getAttribute('aria-label') || '').trim();
            if (ariaLabel) return {name: ariaLabel, source: 'aria-label'};
            const content = window.__auditpilot__.visibleText(el);
            if (content) return {name: content, source: 'content'};
            const value = (el.value || '').trim();
            if (value) return {name: value, source: 'value'};
            const title = (el.getAttribute('title') || '').trim();
            if (title) return {name: title, source: 'title'};
            return {name: '', source: 'none'};
        },
        computeSection(el) {
            const landmark = el.closest(
                'header, nav, footer, main, [role="banner"], [role="navigation"], '
                + '[role="contentinfo"], [role="main"]'
            );
            if (!landmark) return null;
            const role = landmark.getAttribute('role');
            const roleMap = { banner: 'Header', navigation: 'Navigation', contentinfo: 'Footer', main: 'Main content' };
            if (role && roleMap[role]) return roleMap[role];
            const tagMap = { header: 'Header', nav: 'Navigation', footer: 'Footer', main: 'Main content' };
            return tagMap[landmark.tagName.toLowerCase()] || null;
        },
    };
}
"""


class ScraperError(Exception):
    """Raised when a page cannot be reached, loaded, or parsed."""


async def scrape_website(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> ScrapedPageData:
    """Render `url` in a headless browser and extract structured page data.

    Args:
        url: Fully-qualified URL to scrape (validated upstream via Pydantic HttpUrl).
        timeout_ms: Navigation timeout in milliseconds.

    Returns:
        A populated ScrapedPageData instance.

    Raises:
        ScraperError: if the page cannot be reached, times out, returns an
            HTTP error status, or fails to parse for any other reason. Also
            raised (rather than a separate exception type) when the URL
            resolves to a non-public address, so every existing caller's
            error handling covers this without changes.
    """
    try:
        await ensure_public_url(url)
    except UnsafeURLError as exc:
        raise ScraperError(str(exc)) from exc

    browser = None
    try:
        # Every connection the browser makes — redirect hops, iframes,
        # subresources — is re-checked by the egress proxy; the check above
        # only covers the URL as submitted. See egress_proxy.py.
        async with EgressProxy() as egress, async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(headless=True, proxy={"server": egress.server})
            except PlaywrightError as exc:
                raise ScraperError(f"Failed to launch browser: {exc}") from exc

            # A real desktop UA/locale/viewport instead of Playwright's default
            # headless fingerprint — some sites (e.g. dyson.com) 403 outright
            # on the default "HeadlessChrome" identity. See browser_defaults.py.
            context = await browser.new_context(
                user_agent=DESKTOP_USER_AGENT,
                locale=DESKTOP_LOCALE,
                viewport=DESKTOP_VIEWPORT,
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise ScraperError(f"Timed out loading '{url}' after {timeout_ms}ms") from exc
            except PlaywrightError as exc:
                raise ScraperError(egress.refusal(url) or f"Failed to load '{url}': {exc}") from exc

            if response is not None and response.status >= 400:
                raise ScraperError(egress.refusal(url) or f"'{url}' responded with HTTP {response.status}")

            # Recorded for the report's Methodology section: which URL was
            # actually audited (redirects are common and change what "the
            # page" means) and what it responded with.
            return await _extract_page_data(
                page,
                url,
                final_url=response.url if response is not None else None,
                http_status=response.status if response is not None else None,
            )
    except ScraperError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize any unexpected failure
        raise ScraperError(f"Unexpected error scraping '{url}': {exc}") from exc
    finally:
        if browser is not None:
            await browser.close()


async def _extract_page_data(
    page,
    url: str,
    final_url: str | None = None,
    http_status: int | None = None,
) -> ScrapedPageData:
    """Pull structured content out of an already-loaded Playwright page."""

    await page.evaluate(_ELEMENT_HELPERS_SCRIPT)

    title = await page.title()

    meta_description = None
    meta_el = await page.query_selector("meta[name='description']")
    if meta_el is not None:
        meta_description = await meta_el.get_attribute("content")

    h1_tags = await page.eval_on_selector_all(
        "h1", "els => els.map(e => window.__auditpilot__.visibleText(e)).filter(Boolean)"
    )
    h2_tags = await page.eval_on_selector_all(
        "h2", "els => els.map(e => window.__auditpilot__.visibleText(e)).filter(Boolean)"
    )

    # Note: alt is left as returned by getAttribute — `None` means the attribute
    # is absent entirely (a real accessibility problem), while `""` means
    # alt="" is present (valid for intentionally decorative images). Collapsing
    # these would make "missing alt text" checks unreliable.
    raw_images = await page.eval_on_selector_all(
        "img",
        """els => els.map(e => ({
            src: e.src || e.getAttribute('src') || '',
            alt: e.getAttribute('alt'),
            width: e.naturalWidth || null,
            height: e.naturalHeight || null,
            selector: window.__auditpilot__.computeSelector(e),
            section: window.__auditpilot__.computeSection(e),
            dom_excerpt: window.__auditpilot__.domExcerpt(e),
        }))""",
    )
    images = [
        ImageData(
            src=img["src"],
            alt=img["alt"],
            width=img["width"],
            height=img["height"],
            selector=img["selector"],
            section=img["section"],
            dom_excerpt=img.get("dom_excerpt"),
        )
        for img in raw_images
        if img["src"]
    ]

    # Empty-text buttons are intentionally kept (not filtered out) — a button
    # with no accessible name is exactly what the accessibility agent needs
    # to flag.
    raw_buttons = await page.eval_on_selector_all(
        _BUTTON_SELECTOR,
        """els => els.map(e => {
            const text = window.__auditpilot__.visibleText(e);
            const value = (e.value || '').trim();
            const ariaLabel = (e.getAttribute('aria-label') || '').trim();
            const accessible = window.__auditpilot__.accessibleName(e);
            return {
                text: text || value || ariaLabel || '',
                accessible_name: accessible.name,
                name_source: accessible.source,
                id: e.getAttribute('id') || null,
                class_name: (e.getAttribute('class') || '').trim() || null,
                button_type: (e.getAttribute('type') || e.tagName || '').toLowerCase(),
                selector: window.__auditpilot__.computeSelector(e),
                section: window.__auditpilot__.computeSection(e),
                dom_excerpt: window.__auditpilot__.domExcerpt(e),
            };
        })""",
    )
    buttons = [
        ButtonData(
            text=b["text"],
            id=b["id"],
            class_name=b["class_name"],
            button_type=b["button_type"],
            selector=b["selector"],
            section=b["section"],
            accessible_name=b.get("accessible_name"),
            name_source=b.get("name_source"),
            dom_excerpt=b.get("dom_excerpt"),
        )
        for b in raw_buttons
    ]

    raw_links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({text: (e.innerText || '').trim(), href: e.getAttribute('href') || ''}))",
    )
    links = [
        LinkData(text=link["text"] or None, href=link["href"])
        for link in raw_links
        if link["href"]
    ]

    raw_inputs = await page.eval_on_selector_all(
        _INPUT_SELECTOR,
        """els => els.map(e => {
            const id = e.getAttribute('id');
            const type = (e.getAttribute('type') || e.tagName || '').toLowerCase();
            let hasLabel = false;
            if (id) {
                try {
                    const lbl = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                    if (lbl) hasLabel = true;
                } catch (err) { /* invalid selector, ignore */ }
            }
            if (!hasLabel && e.closest('label')) hasLabel = true;
            const ariaLabel = (e.getAttribute('aria-label') || '').trim();
            if (!hasLabel && ariaLabel) hasLabel = true;
            const ariaLabelledby = (e.getAttribute('aria-labelledby') || '').trim();
            if (!hasLabel && ariaLabelledby) hasLabel = true;
            return {type, id, name: e.getAttribute('name'), has_label: hasLabel};
        })""",
    )
    inputs = [
        InputData(type=inp["type"], id=inp["id"], name=inp["name"], has_label=inp["has_label"])
        for inp in raw_inputs
    ]

    raw_og_tags = await page.eval_on_selector_all(
        "meta[property]",
        """els => els
            .filter(e => (e.getAttribute('property') || '').toLowerCase().startsWith('og:'))
            .map(e => ({
                property: (e.getAttribute('property') || '').toLowerCase(),
                content: e.getAttribute('content') || '',
            }))""",
    )
    open_graph = {tag["property"]: tag["content"] for tag in raw_og_tags if tag["property"]}

    return ScrapedPageData(
        url=url,
        final_url=final_url,
        http_status=http_status,
        title=title or None,
        meta_description=meta_description or None,
        h1_tags=h1_tags,
        h2_tags=h2_tags,
        images=images,
        buttons=buttons,
        links=links,
        inputs=inputs,
        open_graph=open_graph,
    )
