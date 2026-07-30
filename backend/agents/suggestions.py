"""
AI-suggestion enrichment (best-effort, post-processing step).

Fills in `Recommendation.ai_suggestion` for a small, bounded set of findings
that a real Gemini call can meaningfully improve on:

  - Missing <title> (SEO's "Missing Title" + Accessibility's "Missing Page
    Title" both flag the same underlying page problem) — a text-only Gemini
    call using real, already-scraped signals (the URL's domain, existing
    <h1> headings, existing meta description, existing og:title) suggests
    one plausible <title>. Skipped entirely if there's nothing but the
    domain to go on, rather than have Gemini invent a title from nothing.

  - Missing alt text on images (SEO + Accessibility both reference the same
    image) — a vision Gemini call on the *actual* image bytes (fetched from
    its own real, already-resolved src) suggests real alt text describing
    what's actually in the picture. Bounded to a handful of distinct images
    so one audit can't trigger dozens of downloads and Gemini calls.

This is deliberately a separate step from AccessibilityAgent/SEOAgent (which
stay synchronous and Gemini-free, easy to unit test without a real API key)
and is always best-effort: any failure along the way — no API key, network
unreachable, image too large, unsupported format, Gemini error or empty
response — just leaves `ai_suggestion` unset on that finding. A report with
one fewer suggestion is fine; a report that silently breaks over a flaky
image download is not.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

from gemini_client import GeminiClient, GeminiClientError
from models.schemas import CategoryResult, Recommendation, ScrapedPageData

logger = logging.getLogger(__name__)

# Recommendation.title values these apply to — must match the `.replace("_",
# " ").title()` output of AccessibilityCheck.MISSING_PAGE_TITLE / SEOCheck.MISSING_TITLE
# and .MISSING_ALT_TEXT / .MISSING_IMAGE_ALT_TEXT (see agents/accessibility.py,
# agents/seo.py).
_TITLE_TITLES = {"Missing Title", "Missing Page Title"}
_ALT_TEXT_TITLES = {"Missing Alt Text", "Missing Image Alt Text"}

_MAX_IMAGE_SUGGESTIONS = 3
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # refuse to fetch/send anything larger than this
_IMAGE_FETCH_TIMEOUT = 8.0


async def enrich_with_ai_suggestions(
    page_data: ScrapedPageData,
    accessibility_result: CategoryResult,
    seo_result: CategoryResult,
    gemini_client: GeminiClient,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> tuple[CategoryResult, CategoryResult]:
    """Returns (accessibility_result, seo_result) with `ai_suggestion` filled
    in on eligible recommendations where generation succeeded. Never raises —
    every failure mode is caught and logged, leaving that suggestion unset.

    `http_client` is exposed purely for tests (inject an httpx.AsyncClient
    backed by a MockTransport instead of hitting the real network) — normal
    callers should leave it unset.
    """

    title_suggestion = await _suggest_title(page_data, gemini_client)
    alt_text_by_src = await _suggest_alt_text(
        accessibility_result, seo_result, gemini_client, http_client=http_client
    )

    if not title_suggestion and not alt_text_by_src:
        return accessibility_result, seo_result

    return (
        _apply_suggestions(accessibility_result, title_suggestion, alt_text_by_src),
        _apply_suggestions(seo_result, title_suggestion, alt_text_by_src),
    )


async def _suggest_title(page_data: ScrapedPageData, gemini_client: GeminiClient) -> Optional[str]:
    if page_data.title and page_data.title.strip():
        return None  # page already has a title — nothing to suggest

    signals: list[str] = []
    host = urlparse(page_data.url).hostname
    if host:
        signals.append(f"Domain: {host}")
    if page_data.h1_tags:
        signals.append(f"Main heading(s): {', '.join(page_data.h1_tags[:3])}")
    if page_data.meta_description:
        signals.append(f"Existing meta description: {page_data.meta_description}")
    og_title = page_data.open_graph.get("og:title")
    if og_title:
        signals.append(f"Existing og:title: {og_title}")

    if len(signals) <= 1:
        # Only (or not even) the domain to go on — a title built from just a
        # hostname would be a guess dressed up as a suggestion, not a real one.
        return None

    prompt = (
        "You are suggesting an HTML <title> tag for a webpage that's missing one. "
        "Base it only on the real signals below — do not invent product names, prices, "
        "or claims that aren't implied by them. Keep it under 60 characters. "
        "Return ONLY the suggested title text, nothing else.\n\n" + "\n".join(signals)
    )
    try:
        suggestion = await gemini_client.generate_content(prompt)
    except GeminiClientError as exc:
        logger.info("suggestion.title skipped reason=%s", exc)
        return None
    return suggestion.strip().strip('"')


async def _suggest_alt_text(
    accessibility_result: CategoryResult,
    seo_result: CategoryResult,
    gemini_client: GeminiClient,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict[str, str]:
    srcs: list[str] = []
    for rec in [*accessibility_result.recommendations, *seo_result.recommendations]:
        if rec.title in _ALT_TEXT_TITLES and rec.context and rec.context not in srcs:
            srcs.append(rec.context)
    srcs = srcs[:_MAX_IMAGE_SUGGESTIONS]

    suggestions: dict[str, str] = {}
    if not srcs:
        return suggestions

    client = http_client or httpx.AsyncClient(timeout=_IMAGE_FETCH_TIMEOUT, follow_redirects=True)
    owns_client = http_client is None
    try:
        for src in srcs:
            try:
                image_bytes, mime_type = await _fetch_image(client, src)
            except Exception as exc:  # noqa: BLE001 - any fetch failure just skips this image
                logger.info("suggestion.alt_text fetch_failed src=%s error=%s", src, exc)
                continue

            prompt = (
                "Write concise, accurate alt text (under 125 characters) describing this "
                "image for a screen reader user. Describe only what's actually visible in "
                "the image — do not invent brand names, prices, or claims you can't see. "
                "Return ONLY the alt text, nothing else."
            )
            try:
                suggestion = await gemini_client.generate_content_with_images(
                    prompt, [image_bytes], mime_type=mime_type
                )
            except GeminiClientError as exc:
                logger.info("suggestion.alt_text skipped src=%s reason=%s", src, exc)
                continue
            suggestions[src] = suggestion.strip().strip('"')
    finally:
        if owns_client:
            await client.aclose()

    return suggestions


async def _fetch_image(client: httpx.AsyncClient, src: str) -> tuple[bytes, str]:
    """Fetches the real image bytes from its own src. Raises on anything that
    makes the result unsafe/unusable — caller treats any exception as
    'skip this image', never as a reason to fail the whole enrichment pass."""
    response = await client.get(src)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/png").split(";")[0].strip()
    if not content_type.startswith("image/"):
        raise ValueError(f"not an image: content-type={content_type}")
    if len(response.content) > _MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    return response.content, content_type


def _apply_suggestions(
    result: CategoryResult,
    title_suggestion: Optional[str],
    alt_text_by_src: dict[str, str],
) -> CategoryResult:
    updated: list[Recommendation] = []
    changed = False
    for rec in result.recommendations:
        suggestion: Optional[str] = None
        if title_suggestion and rec.title in _TITLE_TITLES:
            suggestion = title_suggestion
        elif rec.title in _ALT_TEXT_TITLES and rec.context in alt_text_by_src:
            suggestion = alt_text_by_src[rec.context]

        if suggestion:
            updated.append(rec.model_copy(update={"ai_suggestion": suggestion}))
            changed = True
        else:
            updated.append(rec)

    if not changed:
        return result
    return result.model_copy(update={"recommendations": updated})
