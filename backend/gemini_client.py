"""
Gemini client wrapper (Milestone 4).

Thin, dependency-injectable wrapper around the `google-genai` SDK — the
current, actively supported Google GenAI Python SDK (`pip install
google-genai`, `from google import genai`). The older `google-generativeai`
package has been deprecated by Google in favor of this one; use this module
rather than importing the SDK directly elsewhere.

Construction never fails without an API key — the key is only required (and
validated) the first time `generate_content` is actually called, so agents
can be instantiated freely (e.g. by the orchestrator) in environments where
GEMINI_API_KEY isn't set yet.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

DEFAULT_MODEL_NAME = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.3

logger = logging.getLogger(__name__)


class GeminiClientError(Exception):
    """Raised when Gemini can't be reached, isn't configured, or errors out."""


def _classify_gemini_exception(exc: Exception) -> dict[str, Any]:
    """Best-effort structured breakdown of a Gemini call failure, for logging only.

    A bare `str(exc)` collapses three very different failure shapes into one
    ambiguous string (e.g. "403 Forbidden" could mean any of them):

      1. A genuine Gemini API error (`google.genai.errors.APIError` and its
         subclasses `ClientError`/`ServerError`) — carries a real
         `.code`/`.status`/`.message` from Google itself.
      2. A network/transport-level failure (httpx/requests/urllib3
         exceptions such as `ProxyError`, `ConnectError`, `ConnectTimeout`)
         — the request never reached Google at all; any status-looking
         number in `str(exc)` here describes a proxy or transport hop, not
         a Gemini API response.
      3. Anything else (unexpected SDK/runtime error).

    Distinguishing these matters: (1) means the key/request reached Google
    and Google rejected it (bad key, quota, permission, invalid request);
    (2) means it never got that far (DNS, firewall/proxy/allowlist, TLS,
    timeout) and is not a Gemini-side problem at all.
    """
    info: dict[str, Any] = {
        "exception_type": f"{type(exc).__module__}.{type(exc).__name__}",
        "layer": "unknown",
        "http_status": None,
        "api_error_code": None,
        "api_status": None,
        "api_message": None,
        "is_timeout": False,
    }

    try:
        from google.genai import errors as genai_errors

        if isinstance(exc, genai_errors.APIError):
            info["layer"] = "gemini_api"
            info["http_status"] = getattr(exc, "code", None)
            info["api_error_code"] = getattr(exc, "code", None)
            info["api_status"] = getattr(exc, "status", None)
            info["api_message"] = getattr(exc, "message", None)
    except ImportError:
        pass

    module_name = type(exc).__module__
    type_name = type(exc).__name__
    if info["layer"] == "unknown" and any(
        lib in module_name for lib in ("httpx", "requests", "urllib3", "aiohttp")
    ):
        info["layer"] = "network_transport"

    if isinstance(exc, asyncio.TimeoutError) or "Timeout" in type_name:
        info["is_timeout"] = True

    return info


def _log_gemini_failure(kind: str, exc: Exception, duration: float) -> None:
    info = _classify_gemini_exception(exc)
    logger.warning(
        "gemini.request failed kind=%s duration=%.2fs layer=%s exception_type=%s "
        "http_status=%s api_error_code=%s api_status=%s api_message=%s is_timeout=%s raw_error=%s",
        kind, duration, info["layer"], info["exception_type"], info["http_status"],
        info["api_error_code"], info["api_status"], info["api_message"], info["is_timeout"], exc,
    )


class GeminiClient:
    """Minimal async wrapper around `google.genai.Client.models.generate_content`."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model_name = model_name
        self._client: Any = None  # constructed lazily on first real use

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise GeminiClientError(
                "GEMINI_API_KEY is not set. Export it, add it to your .env, "
                "or pass api_key= to GeminiClient()."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise GeminiClientError(
                "google-genai is not installed (see requirements.txt)"
            ) from exc

        self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_content(self, prompt: str, *, temperature: float = DEFAULT_TEMPERATURE) -> str:
        """Send `prompt` to Gemini and return the raw text response.

        Raises:
            GeminiClientError: if the API key is missing, the SDK isn't
                installed, the request fails, or the response has no text.
        """
        started = time.perf_counter()
        logger.info("gemini.request start kind=text model=%s prompt_chars=%d", self._model_name, len(prompt))

        try:
            client = self._ensure_client()
        except GeminiClientError as exc:
            logger.warning("gemini.request failed kind=text error=%s", exc)
            raise

        try:
            from google.genai import types

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self._model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature),
            )
        except GeminiClientError as exc:
            _log_gemini_failure("text", exc, time.perf_counter() - started)
            raise
        except Exception as exc:  # noqa: BLE001 - normalize any SDK/network failure
            _log_gemini_failure("text", exc, time.perf_counter() - started)
            raise GeminiClientError(f"Gemini request failed: {exc}") from exc

        duration = time.perf_counter() - started
        text = getattr(response, "text", None)
        if not text:
            logger.warning("gemini.request failed kind=text duration=%.2fs error=empty_response", duration)
            raise GeminiClientError("Gemini returned an empty response")

        logger.info("gemini.request done kind=text duration=%.2fs response_chars=%d", duration, len(text))
        return text

    async def generate_content_with_images(
        self,
        prompt: str,
        images: list[bytes],
        *,
        mime_type: str = "image/png",
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        """Like generate_content, but attaches one or more images alongside the prompt.

        Used by VisualAgent to send page screenshots to Gemini's multimodal
        vision model. Images are passed as inline bytes (no upload step) via
        `google.genai.types.Part.from_bytes`.

        Raises:
            GeminiClientError: same failure modes as generate_content.
        """
        started = time.perf_counter()
        logger.info(
            "gemini.request start kind=image model=%s prompt_chars=%d images=%d",
            self._model_name, len(prompt), len(images),
        )

        try:
            client = self._ensure_client()
        except GeminiClientError as exc:
            logger.warning("gemini.request failed kind=image error=%s", exc)
            raise

        try:
            from google.genai import types

            parts = [types.Part.from_bytes(data=image, mime_type=mime_type) for image in images]
            contents = [prompt, *parts]

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self._model_name,
                contents=contents,
                config=types.GenerateContentConfig(temperature=temperature),
            )
        except GeminiClientError as exc:
            _log_gemini_failure("image", exc, time.perf_counter() - started)
            raise
        except Exception as exc:  # noqa: BLE001 - normalize any SDK/network failure
            _log_gemini_failure("image", exc, time.perf_counter() - started)
            raise GeminiClientError(f"Gemini request failed: {exc}") from exc

        duration = time.perf_counter() - started
        text = getattr(response, "text", None)
        if not text:
            logger.warning("gemini.request failed kind=image duration=%.2fs error=empty_response", duration)
            raise GeminiClientError("Gemini returned an empty response")

        logger.info("gemini.request done kind=image duration=%.2fs response_chars=%d", duration, len(text))
        return text
