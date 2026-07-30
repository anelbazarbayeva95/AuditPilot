"""
Visual / screenshot analysis agent (Milestone 11 — second Gemini-powered agent).

Like CopyAgent, this agent doesn't run rule-based checks itself — it sends
the page's screenshots to Gemini's multimodal vision model and asks it to
holistically evaluate four dimensions: visual hierarchy, CTA visibility,
layout issues, and contrast problems. Gemini is instructed to return strict
JSON; this module builds that prompt (see agents/prompts/visual.py), calls
the model, and safely parses/validates the response.

Screenshots are captured once upfront by the caller (report.py/jobs.py, via
screenshot.py) and shared through `context["screenshots"]` — the same
pattern AccessibilityAgent/SEOAgent/CopyAgent use for `context["page_data"]`
— rather than this agent launching its own browser. That keeps a single
Playwright screenshot capture shared across whichever agents need it, and
keeps `analyze_visual` trivially testable with fake PNG bytes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Union

from agents.base import BaseAgent
from agents.prompts.visual import build_visual_prompt
from gemini_client import GeminiClient, GeminiClientError
from models.schemas import AuditCategory, CategoryResult, Recommendation, Severity, VisualResult
from screenshot import PageScreenshots

logger = logging.getLogger(__name__)

# Gemini is asked for raw JSON, but models sometimes wrap it in a markdown
# code fence anyway (```json ... ```) — strip that defensively before parsing.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class VisualAgentError(Exception):
    """Raised when Gemini can't be reached or its response can't be parsed/validated."""


class VisualAgent(BaseAgent):
    category = AuditCategory.VISUAL

    def __init__(self, gemini_client: Optional[GeminiClient] = None) -> None:
        # GeminiClient() never raises without an API key (it's only checked
        # on first real call), so this stays safe to construct eagerly.
        self._gemini_client = gemini_client or GeminiClient()

    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        """BaseAgent entrypoint used by the orchestrator/report builder.

        Expects `context["screenshots"]` to be a PageScreenshots instance or
        an equivalent dict with `full_page_png`/`viewport_png` bytes.
        """
        screenshots = _coerce_screenshots(context.get("screenshots"))
        result = await self.analyze_visual(url, screenshots)

        return CategoryResult(
            category=self.category,
            score=result.score,
            summary=_summarize(result),
            recommendations=[
                Recommendation(
                    title=insight.dimension.value.replace("_", " ").title(),
                    description=insight.point,
                    severity=Severity.MEDIUM,
                    category=AuditCategory.VISUAL,
                )
                for insight in result.recommendations
            ],
            raw_data=result.model_dump(),
        )

    async def analyze_visual(self, url: str, screenshots: PageScreenshots) -> VisualResult:
        """Send `screenshots` to Gemini vision and return the parsed {strengths, weaknesses, recommendations}.

        Raises:
            VisualAgentError: if Gemini can't be reached, or its response
                isn't valid JSON matching the expected schema.
        """
        prompt = build_visual_prompt(url)

        try:
            raw_response = await self._gemini_client.generate_content_with_images(
                prompt, [screenshots.viewport_png, screenshots.full_page_png]
            )
        except GeminiClientError as exc:
            logger.warning("visual_agent.gemini_call failed error=%s", exc)
            raise VisualAgentError(f"Gemini request failed: {exc}") from exc

        try:
            result = _parse_visual_response(raw_response)
        except VisualAgentError as exc:
            logger.warning("visual_agent.parse failed error=%s", exc)
            raise

        logger.info(
            "visual_agent.parse done score=%s strengths=%d weaknesses=%d recommendations=%d",
            result.score, len(result.strengths), len(result.weaknesses), len(result.recommendations),
        )
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_visual_response(raw_response: str) -> VisualResult:
    cleaned = _JSON_FENCE_RE.sub("", raw_response).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise VisualAgentError(
            f"Gemini did not return valid JSON ({exc}). Raw response: {raw_response[:300]!r}"
        ) from exc

    if not isinstance(data, dict):
        raise VisualAgentError(f"Expected a JSON object from Gemini, got: {type(data).__name__}")

    try:
        return VisualResult(**data)
    except Exception as exc:  # pydantic ValidationError, TypeError, etc.
        raise VisualAgentError(f"Gemini response did not match the expected schema: {exc}") from exc


def _summarize(result: VisualResult) -> str:
    score_part = f"Visual score: {result.score:.0f}/100. " if result.score is not None else ""
    return (
        f"{score_part}{len(result.strengths)} strength(s), "
        f"{len(result.weaknesses)} weakness(es), "
        f"{len(result.recommendations)} recommendation(s)."
    )


def _coerce_screenshots(screenshots: Union[PageScreenshots, dict, None]) -> PageScreenshots:
    if isinstance(screenshots, PageScreenshots):
        return screenshots
    if isinstance(screenshots, dict):
        return PageScreenshots(
            full_page_png=screenshots["full_page_png"], viewport_png=screenshots["viewport_png"]
        )
    raise ValueError(
        "VisualAgent requires context['screenshots'] (PageScreenshots or a dict with "
        "full_page_png/viewport_png bytes)"
    )
