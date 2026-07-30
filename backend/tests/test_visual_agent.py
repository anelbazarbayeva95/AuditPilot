"""
Unit tests for VisualAgent (Milestone 11).

Uses a FakeGeminiClient so these tests never touch the network, a real
GEMINI_API_KEY, or a real Playwright browser — they verify image/prompt
wiring, response parsing (including markdown-fence stripping), error
handling for malformed/invalid responses, and the async `analyze()`
orchestrator entrypoint.
"""

from __future__ import annotations

import json

import pytest

from agents.visual import VisualAgent, VisualAgentError
from gemini_client import GeminiClientError
from models.schemas import AuditCategory
from screenshot import PageScreenshots

_VALID_RESPONSE = {
    "strengths": [
        {"dimension": "visual_hierarchy", "point": "The hero headline is the largest element on the page."}
    ],
    "weaknesses": [
        {"dimension": "cta_visibility", "point": "The primary CTA button sits below the fold."}
    ],
    "recommendations": [
        {"dimension": "cta_visibility", "point": "Move the primary CTA above the fold."}
    ],
    "score": 68,
}


class FakeGeminiClient:
    """Stand-in for GeminiClient that returns a canned response or raises."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_prompt: str | None = None
        self.last_images: list[bytes] | None = None

    async def generate_content_with_images(self, prompt: str, images: list[bytes], **kwargs) -> str:
        self.last_prompt = prompt
        self.last_images = images
        if self.error is not None:
            raise self.error
        return self.response


def make_screenshots() -> PageScreenshots:
    return PageScreenshots(full_page_png=b"full-page-bytes", viewport_png=b"viewport-bytes")


class TestAnalyzeVisualParsing:
    async def test_parses_valid_json_response(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = VisualAgent(gemini_client=fake_client)

        result = await agent.analyze_visual("https://example.com", make_screenshots())

        assert result.score == 68
        assert len(result.strengths) == 1
        assert result.strengths[0].dimension.value == "visual_hierarchy"
        assert len(result.weaknesses) == 1
        assert len(result.recommendations) == 1

    async def test_strips_markdown_json_fence(self):
        fenced = "```json\n" + json.dumps(_VALID_RESPONSE) + "\n```"
        fake_client = FakeGeminiClient(response=fenced)
        agent = VisualAgent(gemini_client=fake_client)

        result = await agent.analyze_visual("https://example.com", make_screenshots())
        assert result.score == 68

    async def test_strips_bare_markdown_fence(self):
        fenced = "```\n" + json.dumps(_VALID_RESPONSE) + "\n```"
        fake_client = FakeGeminiClient(response=fenced)
        agent = VisualAgent(gemini_client=fake_client)

        result = await agent.analyze_visual("https://example.com", make_screenshots())
        assert result.score == 68

    async def test_both_screenshots_sent_to_client_viewport_first(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = VisualAgent(gemini_client=fake_client)

        screenshots = make_screenshots()
        await agent.analyze_visual("https://example.com", screenshots)

        assert fake_client.last_images == [screenshots.viewport_png, screenshots.full_page_png]

    async def test_prompt_includes_url(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = VisualAgent(gemini_client=fake_client)

        await agent.analyze_visual("https://unique-marker.example.com", make_screenshots())
        assert "unique-marker.example.com" in fake_client.last_prompt


class TestAnalyzeVisualErrors:
    async def test_raises_on_invalid_json(self):
        fake_client = FakeGeminiClient(response="not json at all {{{")
        agent = VisualAgent(gemini_client=fake_client)

        with pytest.raises(VisualAgentError, match="did not return valid JSON"):
            await agent.analyze_visual("https://example.com", make_screenshots())

    async def test_raises_on_non_object_json(self):
        fake_client = FakeGeminiClient(response=json.dumps(["not", "a", "dict"]))
        agent = VisualAgent(gemini_client=fake_client)

        with pytest.raises(VisualAgentError, match="Expected a JSON object"):
            await agent.analyze_visual("https://example.com", make_screenshots())

    async def test_raises_on_schema_mismatch(self):
        bad_response = {
            "strengths": [{"dimension": "not_a_real_dimension", "point": "x"}],
            "weaknesses": [],
            "recommendations": [],
        }
        fake_client = FakeGeminiClient(response=json.dumps(bad_response))
        agent = VisualAgent(gemini_client=fake_client)

        with pytest.raises(VisualAgentError, match="did not match the expected schema"):
            await agent.analyze_visual("https://example.com", make_screenshots())

    async def test_propagates_gemini_client_error(self):
        fake_client = FakeGeminiClient(error=GeminiClientError("network down"))
        agent = VisualAgent(gemini_client=fake_client)

        with pytest.raises(VisualAgentError, match="Gemini request failed"):
            await agent.analyze_visual("https://example.com", make_screenshots())


class TestAnalyzeWrapper:
    async def test_analyze_returns_category_result(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = VisualAgent(gemini_client=fake_client)

        category_result = await agent.analyze("https://example.com", {"screenshots": make_screenshots()})

        assert category_result.category == AuditCategory.VISUAL
        assert category_result.score == 68
        assert len(category_result.recommendations) == 1
        assert category_result.recommendations[0].category == AuditCategory.VISUAL
        assert category_result.raw_data["score"] == 68

    async def test_analyze_accepts_plain_dict_screenshots(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = VisualAgent(gemini_client=fake_client)

        screenshots_dict = {"full_page_png": b"full", "viewport_png": b"vp"}
        category_result = await agent.analyze("https://example.com", {"screenshots": screenshots_dict})
        assert category_result.score == 68

    async def test_analyze_raises_on_missing_screenshots(self):
        agent = VisualAgent(gemini_client=FakeGeminiClient(response="{}"))
        with pytest.raises(ValueError):
            await agent.analyze("https://example.com", {})

    async def test_analyze_propagates_visual_agent_error(self):
        fake_client = FakeGeminiClient(response="not json")
        agent = VisualAgent(gemini_client=fake_client)

        with pytest.raises(VisualAgentError):
            await agent.analyze("https://example.com", {"screenshots": make_screenshots()})
