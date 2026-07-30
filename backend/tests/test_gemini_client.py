"""
Unit tests for GeminiClient (Milestone 4).

No network access or real API key is used — these tests only verify the
lazy-initialization contract (construction never requires an API key; it's
only checked on first real call) and error wrapping, against the
`google-genai` SDK shape (`client.models.generate_content(...)`).
"""

from __future__ import annotations

import pytest

from gemini_client import GeminiClient, GeminiClientError


class _FakeModels:
    """Stands in for genai.Client().models."""

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.last_call: dict | None = None

    def generate_content(self, *, model, contents, config=None):
        self.last_call = {"model": model, "contents": contents, "config": config}
        if self._error is not None:
            raise self._error
        return self._response


class _FakeGenaiClient:
    """Stands in for google.genai.Client — only the `.models` attribute is used."""

    def __init__(self, response=None, error: Exception | None = None):
        self.models = _FakeModels(response=response, error=error)


class _Response:
    def __init__(self, text: str):
        self.text = text


def test_construction_never_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Should not raise.
    GeminiClient()


async def test_generate_content_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)

    with pytest.raises(GeminiClientError, match="GEMINI_API_KEY"):
        await client.generate_content("hello")


async def test_generate_content_wraps_sdk_failure():
    client = GeminiClient(api_key="fake-key-for-test")
    client._client = _FakeGenaiClient(error=RuntimeError("boom"))

    with pytest.raises(GeminiClientError, match="Gemini request failed"):
        await client.generate_content("hello")


async def test_generate_content_raises_on_empty_response():
    client = GeminiClient(api_key="fake-key-for-test")
    client._client = _FakeGenaiClient(response=_Response(""))

    with pytest.raises(GeminiClientError, match="empty response"):
        await client.generate_content("hello")


async def test_generate_content_returns_text_on_success():
    client = GeminiClient(api_key="fake-key-for-test")
    client._client = _FakeGenaiClient(response=_Response("some model output"))

    result = await client.generate_content("hello")
    assert result == "some model output"


async def test_generate_content_passes_model_and_prompt_through():
    client = GeminiClient(api_key="fake-key-for-test", model_name="gemini-2.5-flash")
    fake_client = _FakeGenaiClient(response=_Response("ok"))
    client._client = fake_client

    await client.generate_content("my prompt", temperature=0.7)

    assert fake_client.models.last_call["model"] == "gemini-2.5-flash"
    assert fake_client.models.last_call["contents"] == "my prompt"
    assert fake_client.models.last_call["config"].temperature == 0.7


# ---------------------------------------------------------------------------
# generate_content_with_images (Milestone 11 — VisualAgent)
# ---------------------------------------------------------------------------

async def test_generate_content_with_images_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)

    with pytest.raises(GeminiClientError, match="GEMINI_API_KEY"):
        await client.generate_content_with_images("hello", [b"fake-png-bytes"])


async def test_generate_content_with_images_wraps_sdk_failure():
    client = GeminiClient(api_key="fake-key-for-test")
    client._client = _FakeGenaiClient(error=RuntimeError("boom"))

    with pytest.raises(GeminiClientError, match="Gemini request failed"):
        await client.generate_content_with_images("hello", [b"fake-png-bytes"])


async def test_generate_content_with_images_raises_on_empty_response():
    client = GeminiClient(api_key="fake-key-for-test")
    client._client = _FakeGenaiClient(response=_Response(""))

    with pytest.raises(GeminiClientError, match="empty response"):
        await client.generate_content_with_images("hello", [b"fake-png-bytes"])


async def test_generate_content_with_images_sends_prompt_and_image_parts():
    client = GeminiClient(api_key="fake-key-for-test", model_name="gemini-2.5-flash")
    fake_client = _FakeGenaiClient(response=_Response("visual analysis"))
    client._client = fake_client

    result = await client.generate_content_with_images("describe this page", [b"png-one", b"png-two"])

    assert result == "visual analysis"
    contents = fake_client.models.last_call["contents"]
    assert contents[0] == "describe this page"
    assert len(contents) == 3  # prompt + 2 image parts
    # Each image part wraps the original bytes (google.genai.types.Part.from_bytes).
    assert contents[1].inline_data.data == b"png-one"
    assert contents[2].inline_data.data == b"png-two"
