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
from agents.prioritization import prioritize
from agents.prompts.visual import build_visual_prompt
from gemini_client import GeminiClient, GeminiClientError
from labels import humanize, pluralize
from models.schemas import (
    AuditCategory,
    CategoryCoverage,
    CategoryResult,
    CoverageMethod,
    DetectionMethod,
    Recommendation,
    ScoreStatus,
    ScreenshotQuality,
    Severity,
    VisualDimension,
    VisualResult,
)
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
            score_explanation=(
                "Gemini's holistic 0-100 visual design score, reported as-is. This is a model "
                "judgment over the captured screenshots, not a deduction-based measurement."
            ),
            coverage=coverage(),
            summary=_summarize(result),
            recommendations=[
                prioritize(
                    Recommendation(
                        title=humanize(insight.dimension),
                        description=insight.point,
                        severity=Severity.MEDIUM,
                        category=AuditCategory.VISUAL,
                        rule_id=insight.dimension.value,
                        detection=DetectionMethod.AI_GENERATED,
                        confidence=insight.confidence,
                    )
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


def coverage() -> CategoryCoverage:
    """The four dimensions judged from screenshots, and what screenshots can't show."""
    return CategoryCoverage(
        checks_run=[humanize(dimension) for dimension in VisualDimension],
        checks_not_covered=[
            "Measured color contrast ratios (see Accessibility)",
            "Responsive behavior at other breakpoints",
            "Interactive, hover, and focus states",
            "Animation and scroll behavior",
            "Rendering in other browsers",
        ],
        method=CoverageMethod.AI_ASSISTED,
        notes=(
            "Model-generated judgment over a desktop viewport and full-page screenshot of a single "
            "URL. Observations are opinions with stated confidence, not measurements."
        ),
    )


def insufficient_evidence_result(quality: ScreenshotQuality | None) -> CategoryResult:
    """The result to publish when the capture isn't good enough to judge.

    This is the fix for the failure mode where the pipeline evaluated a mostly
    blank render and produced confident praise for a hero section that wasn't
    in its own screenshot. "We couldn't see the page well enough to assess it"
    is a legitimate audit outcome; inventing an assessment from a blank image
    is not, so the category returns no score at all and says why.
    """
    reason = (quality.reason if quality and quality.reason else None) or (
        "The captured screenshot could not be verified as a complete render of the page."
    )
    return CategoryResult(
        category=AuditCategory.VISUAL,
        score=None,
        score_status=ScoreStatus.INSUFFICIENT_EVIDENCE,
        score_explanation=(
            "No visual score: the page render was incomplete, so there was nothing reliable to "
            "assess. Scoring it anyway would describe the capture, not the page."
        ),
        coverage=CategoryCoverage(
            checks_run=[],
            checks_not_covered=[humanize(dimension) for dimension in VisualDimension],
            method=CoverageMethod.NOT_RUN,
            notes=reason,
        ),
        summary=f"Visual analysis was not performed. {reason}",
        recommendations=[],
        raw_data=None,
    )


def _summarize(result: VisualResult) -> str:
    score_part = f"Visual score: {result.score:.0f}/100. " if result.score is not None else ""
    return (
        f"{score_part}{pluralize(len(result.strengths), 'strength')}, "
        f"{pluralize(len(result.weaknesses), 'weakness', 'weaknesses')}, "
        f"{pluralize(len(result.recommendations), 'recommendation')}."
    )


def _coerce_screenshots(screenshots: Union[PageScreenshots, dict, None]) -> PageScreenshots:
    if isinstance(screenshots, PageScreenshots):
        return screenshots
    if isinstance(screenshots, dict):
        return PageScreenshots(
            full_page_png=screenshots["full_page_png"],
            viewport_png=screenshots["viewport_png"],
            quality=screenshots.get("quality"),
        )
    raise ValueError(
        "VisualAgent requires context['screenshots'] (PageScreenshots or a dict with "
        "full_page_png/viewport_png bytes)"
    )
