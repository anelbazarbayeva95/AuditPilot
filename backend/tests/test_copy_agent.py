"""
Unit tests for CopyAgent (Milestone 4).

Uses a FakeGeminiClient so these tests never touch the network or require a
real GEMINI_API_KEY — they verify prompt wiring, response parsing (including
markdown-fence stripping), error handling for malformed/invalid responses,
and the async `analyze()` orchestrator entrypoint.
"""

from __future__ import annotations

import json

import pytest

from agents.copy import CopyAgent, CopyAgentError
from gemini_client import GeminiClientError
from models.schemas import AuditCategory, ScrapedPageData

_VALID_RESPONSE = {
    "strengths": [
        {"dimension": "value_proposition_clarity", "point": "The h1 clearly states what the product does."}
    ],
    "weaknesses": [
        {"dimension": "cta_quality", "point": "The only button says 'Submit', which is generic."}
    ],
    "recommendations": [
        {"dimension": "cta_quality", "point": "Change 'Submit' to a specific action like 'Start free trial'."}
    ],
    "score": 72,
}


class FakeGeminiClient:
    """Stand-in for GeminiClient that returns a canned response or raises."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_prompt: str | None = None

    async def generate_content(self, prompt: str, **kwargs) -> str:
        self.last_prompt = prompt
        if self.error is not None:
            raise self.error
        return self.response


def make_page(**overrides) -> ScrapedPageData:
    defaults = dict(
        url="https://example.com",
        title="Acme Widgets",
        meta_description="Ship widgets faster.",
        h1_tags=["Ship widgets faster"],
        h2_tags=[],
        images=[],
        buttons=[],
        links=[],
        inputs=[],
    )
    defaults.update(overrides)
    return ScrapedPageData(**defaults)


class TestAnalyzeCopyParsing:
    async def test_parses_valid_json_response(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = CopyAgent(gemini_client=fake_client)

        result = await agent.analyze_copy(make_page())

        assert result.score == 72
        assert len(result.strengths) == 1
        assert result.strengths[0].dimension.value == "value_proposition_clarity"
        assert len(result.weaknesses) == 1
        assert len(result.recommendations) == 1

    async def test_strips_markdown_json_fence(self):
        fenced = "```json\n" + json.dumps(_VALID_RESPONSE) + "\n```"
        fake_client = FakeGeminiClient(response=fenced)
        agent = CopyAgent(gemini_client=fake_client)

        result = await agent.analyze_copy(make_page())
        assert result.score == 72

    async def test_strips_bare_markdown_fence(self):
        fenced = "```\n" + json.dumps(_VALID_RESPONSE) + "\n```"
        fake_client = FakeGeminiClient(response=fenced)
        agent = CopyAgent(gemini_client=fake_client)

        result = await agent.analyze_copy(make_page())
        assert result.score == 72

    async def test_prompt_is_sent_to_client(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = CopyAgent(gemini_client=fake_client)

        await agent.analyze_copy(make_page(title="Unique Title Marker"))
        assert "Unique Title Marker" in fake_client.last_prompt


class TestAnalyzeCopyErrors:
    async def test_raises_on_invalid_json(self):
        fake_client = FakeGeminiClient(response="not json at all {{{")
        agent = CopyAgent(gemini_client=fake_client)

        with pytest.raises(CopyAgentError, match="did not return valid JSON"):
            await agent.analyze_copy(make_page())

    async def test_raises_on_non_object_json(self):
        fake_client = FakeGeminiClient(response=json.dumps(["not", "a", "dict"]))
        agent = CopyAgent(gemini_client=fake_client)

        with pytest.raises(CopyAgentError, match="Expected a JSON object"):
            await agent.analyze_copy(make_page())

    async def test_raises_on_schema_mismatch_missing_keys(self):
        fake_client = FakeGeminiClient(response=json.dumps({"strengths": []}))
        # Missing weaknesses/recommendations should still validate since they
        # default to empty lists — instead test an invalid dimension enum,
        # which *should* fail schema validation.
        bad_response = {
            "strengths": [{"dimension": "not_a_real_dimension", "point": "x"}],
            "weaknesses": [],
            "recommendations": [],
        }
        fake_client = FakeGeminiClient(response=json.dumps(bad_response))
        agent = CopyAgent(gemini_client=fake_client)

        with pytest.raises(CopyAgentError, match="did not match the expected schema"):
            await agent.analyze_copy(make_page())

    async def test_propagates_gemini_client_error(self):
        fake_client = FakeGeminiClient(error=GeminiClientError("network down"))
        agent = CopyAgent(gemini_client=fake_client)

        with pytest.raises(CopyAgentError, match="Gemini request failed"):
            await agent.analyze_copy(make_page())


class TestAnalyzeWrapper:
    async def test_analyze_returns_category_result(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = CopyAgent(gemini_client=fake_client)

        category_result = await agent.analyze("https://example.com", {"page_data": make_page()})

        assert category_result.category == AuditCategory.COPY
        assert category_result.score == 72
        assert len(category_result.recommendations) == 1
        assert category_result.recommendations[0].category == AuditCategory.COPY
        assert category_result.raw_data["score"] == 72

    async def test_analyze_accepts_plain_dict_page_data(self):
        fake_client = FakeGeminiClient(response=json.dumps(_VALID_RESPONSE))
        agent = CopyAgent(gemini_client=fake_client)

        page_dict = make_page().model_dump()
        category_result = await agent.analyze("https://example.com", {"page_data": page_dict})
        assert category_result.score == 72

    async def test_analyze_raises_on_missing_page_data(self):
        agent = CopyAgent(gemini_client=FakeGeminiClient(response="{}"))
        with pytest.raises(ValueError):
            await agent.analyze("https://example.com", {})

    async def test_analyze_propagates_copy_agent_error(self):
        fake_client = FakeGeminiClient(response="not json")
        agent = CopyAgent(gemini_client=fake_client)

        with pytest.raises(CopyAgentError):
            await agent.analyze("https://example.com", {"page_data": make_page()})
