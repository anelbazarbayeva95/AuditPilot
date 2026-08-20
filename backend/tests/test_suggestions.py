"""
Unit tests for the AI-suggestion enrichment pass (agents/suggestions.py).

Uses a FakeGeminiClient (never touches the real Gemini API) and an
httpx.AsyncClient backed by MockTransport (never touches the real network),
so these tests are fully offline and deterministic.
"""

from __future__ import annotations

import httpx

from agents.suggestions import (
    _is_alt_text_finding,
    _is_title_finding,
    enrich_with_ai_suggestions,
)
from gemini_client import GeminiClientError
from models.schemas import AuditCategory, CategoryResult, Recommendation, ScrapedPageData, Severity


class FakeGeminiClient:
    """Stand-in for GeminiClient with separately controllable text/image responses."""

    def __init__(
        self,
        text_response: str | None = None,
        text_error: Exception | None = None,
        image_response: str | None = None,
        image_error: Exception | None = None,
    ):
        self.text_response = text_response
        self.text_error = text_error
        self.image_response = image_response
        self.image_error = image_error
        self.text_prompts: list[str] = []
        self.image_calls: list[tuple[str, list[bytes], str]] = []

    async def generate_content(self, prompt: str, **kwargs) -> str:
        self.text_prompts.append(prompt)
        if self.text_error is not None:
            raise self.text_error
        return self.text_response

    async def generate_content_with_images(
        self, prompt: str, images: list[bytes], *, mime_type: str = "image/png", **kwargs
    ) -> str:
        self.image_calls.append((prompt, images, mime_type))
        if self.image_error is not None:
            raise self.image_error
        return self.image_response


def make_page(**overrides) -> ScrapedPageData:
    defaults = dict(
        url="https://example.com",
        title=None,
        meta_description=None,
        h1_tags=[],
        h2_tags=[],
        images=[],
        buttons=[],
        links=[],
        inputs=[],
    )
    defaults.update(overrides)
    return ScrapedPageData(**defaults)


def make_result(recommendations: list[Recommendation], category=AuditCategory.ACCESSIBILITY) -> CategoryResult:
    return CategoryResult(category=category, score=80.0, summary=None, recommendations=recommendations)


def title_rec(title: str, category=AuditCategory.ACCESSIBILITY) -> Recommendation:
    return Recommendation(title=title, description="A finding.", severity=Severity.HIGH, category=category)


def alt_text_rec(title: str, src: str, category=AuditCategory.ACCESSIBILITY) -> Recommendation:
    return Recommendation(
        title=title, description="A finding.", severity=Severity.HIGH, category=category, context=src
    )


def mock_http_client(
    content: bytes = b"fake-bytes", content_type: str = "image/png", status_code: int = 200
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers={"content-type": content_type}, content=content)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestTitleSuggestion:
    async def test_suggests_title_when_missing_and_signals_exist(self):
        page = make_page(h1_tags=["Ship widgets faster"])
        gemini = FakeGeminiClient(text_response='"Acme - Ship Widgets Faster"')
        accessibility = make_result([title_rec("Missing Page Title")])
        seo = make_result([title_rec("Missing Title", category=AuditCategory.SEO)], category=AuditCategory.SEO)

        new_a11y, new_seo = await enrich_with_ai_suggestions(page, accessibility, seo, gemini)

        assert new_a11y.recommendations[0].ai_suggestion == "Acme - Ship Widgets Faster"
        assert new_seo.recommendations[0].ai_suggestion == "Acme - Ship Widgets Faster"
        # One shared suggestion for the shared underlying problem, not one Gemini call per category.
        assert len(gemini.text_prompts) == 1

    async def test_skips_when_page_already_has_title(self):
        page = make_page(title="Already Set", h1_tags=["Ship widgets faster"])
        gemini = FakeGeminiClient(text_response="should not be used")
        accessibility = make_result([])
        seo = make_result([], category=AuditCategory.SEO)

        await enrich_with_ai_suggestions(page, accessibility, seo, gemini)
        assert gemini.text_prompts == []

    async def test_skips_when_no_real_signals_beyond_domain(self):
        # No h1, no meta description, no og:title — only the bare domain,
        # which isn't enough to base a real suggestion on.
        page = make_page(title=None)
        gemini = FakeGeminiClient(text_response="should not be used")
        accessibility = make_result([title_rec("Missing Page Title")])
        seo = make_result([], category=AuditCategory.SEO)

        new_a11y, _ = await enrich_with_ai_suggestions(page, accessibility, seo, gemini)
        assert gemini.text_prompts == []
        assert new_a11y.recommendations[0].ai_suggestion is None

    async def test_gemini_failure_leaves_suggestion_unset(self):
        page = make_page(h1_tags=["Ship widgets faster"])
        gemini = FakeGeminiClient(text_error=GeminiClientError("rate limited"))
        accessibility = make_result([title_rec("Missing Page Title")])
        seo = make_result([], category=AuditCategory.SEO)

        new_a11y, _ = await enrich_with_ai_suggestions(page, accessibility, seo, gemini)
        assert new_a11y.recommendations[0].ai_suggestion is None


class TestAltTextSuggestion:
    async def test_suggests_alt_text_for_real_fetched_image(self):
        page = make_page(title="Has a title")
        gemini = FakeGeminiClient(image_response='"A red bicycle leaning against a brick wall"')
        rec = alt_text_rec("Missing Alt Text", "https://example.com/bike.jpg")
        accessibility = make_result([rec])
        seo = make_result([], category=AuditCategory.SEO)

        http_client = mock_http_client(content=b"jpeg-bytes", content_type="image/jpeg")
        try:
            new_a11y, _ = await enrich_with_ai_suggestions(
                page, accessibility, seo, gemini, http_client=http_client
            )
        finally:
            await http_client.aclose()

        assert new_a11y.recommendations[0].ai_suggestion == "A red bicycle leaning against a brick wall"
        assert len(gemini.image_calls) == 1
        _, images, mime_type = gemini.image_calls[0]
        assert images == [b"jpeg-bytes"]
        assert mime_type == "image/jpeg"

    async def test_non_image_content_type_is_skipped(self):
        page = make_page(title="Has a title")
        gemini = FakeGeminiClient(image_response="should not be used")
        rec = alt_text_rec("Missing Alt Text", "https://example.com/not-really-an-image")
        accessibility = make_result([rec])
        seo = make_result([], category=AuditCategory.SEO)

        http_client = mock_http_client(content=b"<html>not an image</html>", content_type="text/html")
        try:
            new_a11y, _ = await enrich_with_ai_suggestions(
                page, accessibility, seo, gemini, http_client=http_client
            )
        finally:
            await http_client.aclose()

        assert new_a11y.recommendations[0].ai_suggestion is None
        assert gemini.image_calls == []

    async def test_same_image_flagged_by_both_categories_gets_one_fetch(self):
        page = make_page(title="Has a title")
        gemini = FakeGeminiClient(image_response="A logo")
        src = "https://example.com/logo.png"
        accessibility = make_result([alt_text_rec("Missing Alt Text", src)])
        seo = make_result(
            [alt_text_rec("Missing Image Alt Text", src, category=AuditCategory.SEO)],
            category=AuditCategory.SEO,
        )

        http_client = mock_http_client()
        try:
            new_a11y, new_seo = await enrich_with_ai_suggestions(
                page, accessibility, seo, gemini, http_client=http_client
            )
        finally:
            await http_client.aclose()

        assert new_a11y.recommendations[0].ai_suggestion == "A logo"
        assert new_seo.recommendations[0].ai_suggestion == "A logo"
        assert len(gemini.image_calls) == 1  # deduped by src, not fetched/suggested twice

    async def test_gemini_failure_leaves_alt_suggestion_unset(self):
        page = make_page(title="Has a title")
        gemini = FakeGeminiClient(image_error=GeminiClientError("rate limited"))
        rec = alt_text_rec("Missing Alt Text", "https://example.com/bike.jpg")
        accessibility = make_result([rec])
        seo = make_result([], category=AuditCategory.SEO)

        http_client = mock_http_client()
        try:
            new_a11y, _ = await enrich_with_ai_suggestions(
                page, accessibility, seo, gemini, http_client=http_client
            )
        finally:
            await http_client.aclose()

        assert new_a11y.recommendations[0].ai_suggestion is None


class TestFindingMatching:
    """Enrichment must key off rule_id, not the editorial title.

    Titles are report copy and have been reworded once already; matching on
    them silently switched this whole pass off when that happened.
    """

    async def test_matches_real_agent_output(self):
        """The titles and rule ids the agents actually emit today."""
        from agents.accessibility import AccessibilityAgent
        from models.schemas import ImageData

        page = make_page(images=[ImageData(src="https://example.com/hero.png", alt=None)])
        result = await AccessibilityAgent().analyze("https://example.com", {"page_data": page})
        alt_recs = [r for r in result.recommendations if _is_alt_text_finding(r)]

        assert len(alt_recs) == 1
        assert alt_recs[0].rule_id == "missing_alt_text"

    def test_rule_id_takes_precedence_over_title(self):
        rec = Recommendation(
            title="Some reworded label", description="d", severity=Severity.HIGH,
            category=AuditCategory.ACCESSIBILITY, rule_id="missing_page_title",
        )

        assert _is_title_finding(rec)

    def test_falls_back_to_title_when_rule_id_is_absent(self):
        """Recommendations built before rule_id existed still enrich."""
        assert _is_title_finding(title_rec("Missing Page Title"))
        assert _is_alt_text_finding(alt_text_rec("Missing Alt Text", "https://x/i.png"))

    def test_unrelated_findings_are_not_matched(self):
        rec = Recommendation(
            title="Button with no accessible name", description="d", severity=Severity.HIGH,
            category=AuditCategory.ACCESSIBILITY, rule_id="empty_button",
        )

        assert not _is_title_finding(rec)
        assert not _is_alt_text_finding(rec)
