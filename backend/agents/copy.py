"""
Copy / messaging quality agent (Milestone 4 — first Gemini-powered agent).

Unlike the accessibility/SEO agents (static rule checks), this agent sends
scraped page copy to Gemini and asks it to holistically evaluate five
dimensions: value proposition clarity, readability, CTA quality, jargon, and
trust signals. Gemini is instructed to return strict JSON; this module is
responsible for building that prompt (see agents/prompts/copy.py), calling
the model, and safely parsing/validating the response.

`analyze_copy` is the core async method (Gemini call + parsing), independent
of the CategoryResult wrapper — this is what unit tests exercise directly
with a fake Gemini client, with no network access or API key required.
`analyze` is the async BaseAgent-interface entrypoint the orchestrator calls.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Union

from agents.base import BaseAgent
from agents.prompts.copy import build_copy_prompt
from gemini_client import GeminiClient, GeminiClientError
from models.schemas import (
    AuditCategory,
    CategoryResult,
    CopyResult,
    Recommendation,
    ScrapedPageData,
    Severity,
)

logger = logging.getLogger(__name__)

# Gemini is asked for raw JSON, but models sometimes wrap it in a markdown
# code fence anyway (```json ... ```) — strip that defensively before parsing.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class CopyAgentError(Exception):
    """Raised when Gemini can't be reached or its response can't be parsed/validated."""


class CopyAgent(BaseAgent):
    category = AuditCategory.COPY

    def __init__(self, gemini_client: Optional[GeminiClient] = None) -> None:
        # GeminiClient() never raises without an API key (it's only checked
        # on first real call), so this stays safe to construct eagerly
        # (e.g. by Orchestrator.__init__) even before GEMINI_API_KEY is set.
        self._gemini_client = gemini_client or GeminiClient()

    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        """BaseAgent entrypoint used by the orchestrator.

        Expects `context["page_data"]` to be a ScrapedPageData instance or an
        equivalent dict (e.g. from `orchestrator._scrape`).
        """
        page_data = _coerce_page_data(context.get("page_data"))
        result = await self.analyze_copy(page_data)

        return CategoryResult(
            category=self.category,
            score=result.score,
            summary=_summarize(result),
            recommendations=[
                Recommendation(
                    title=insight.dimension.value.replace("_", " ").title(),
                    description=insight.point,
                    severity=Severity.MEDIUM,
                    category=AuditCategory.COPY,
                )
                for insight in result.recommendations
            ],
            raw_data=result.model_dump(),
        )

    async def analyze_copy(self, page_data: ScrapedPageData) -> CopyResult:
        """Send `page_data` to Gemini and return the parsed {strengths, weaknesses, recommendations}.

        Raises:
            CopyAgentError: if Gemini can't be reached, or its response isn't
                valid JSON matching the expected schema.
        """
        prompt = build_copy_prompt(page_data)

        try:
            raw_response = await self._gemini_client.generate_content(prompt)
        except GeminiClientError as exc:
            logger.warning("copy_agent.gemini_call failed error=%s", exc)
            raise CopyAgentError(f"Gemini request failed: {exc}") from exc

        try:
            result = _parse_copy_response(raw_response)
        except CopyAgentError as exc:
            logger.warning("copy_agent.parse failed error=%s", exc)
            raise

        logger.info(
            "copy_agent.parse done score=%s strengths=%d weaknesses=%d recommendations=%d",
            result.score, len(result.strengths), len(result.weaknesses), len(result.recommendations),
        )
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_copy_response(raw_response: str) -> CopyResult:
    cleaned = _JSON_FENCE_RE.sub("", raw_response).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise CopyAgentError(
            f"Gemini did not return valid JSON ({exc}). Raw response: {raw_response[:300]!r}"
        ) from exc

    if not isinstance(data, dict):
        raise CopyAgentError(f"Expected a JSON object from Gemini, got: {type(data).__name__}")

    try:
        return CopyResult(**data)
    except Exception as exc:  # pydantic ValidationError, TypeError, etc.
        raise CopyAgentError(f"Gemini response did not match the expected schema: {exc}") from exc


def _summarize(result: CopyResult) -> str:
    score_part = f"Copy score: {result.score:.0f}/100. " if result.score is not None else ""
    return (
        f"{score_part}{len(result.strengths)} strength(s), "
        f"{len(result.weaknesses)} weakness(es), "
        f"{len(result.recommendations)} recommendation(s)."
    )


def _coerce_page_data(page_data: Union[ScrapedPageData, dict, None]) -> ScrapedPageData:
    if isinstance(page_data, ScrapedPageData):
        return page_data
    if isinstance(page_data, dict):
        return ScrapedPageData(**page_data)
    raise ValueError("CopyAgent requires context['page_data'] (ScrapedPageData or dict)")
