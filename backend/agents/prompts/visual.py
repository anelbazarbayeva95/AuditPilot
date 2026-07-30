"""
Prompt template for VisualAgent (Milestone 11).

Kept separate from agents/visual.py so the prompt wording can be iterated on
independently of the parsing/error-handling logic, following the same split
used for CopyAgent (see agents/prompts/copy.py).
"""

from __future__ import annotations

VISUAL_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior product designer and UX auditor reviewing screenshots of a \
live website. You give specific, evidence-based feedback grounded only in \
what is visibly present in the images — never invent elements you can't see."""

VISUAL_ANALYSIS_USER_TEMPLATE = """\
You are given two screenshots of the same webpage ({url}):
1. The ABOVE-THE-FOLD VIEWPORT — exactly what a visitor sees before scrolling.
2. The FULL PAGE — the entire page from top to bottom.

Analyze both images across exactly these four dimensions:

1. visual_hierarchy — Does the layout guide the eye to the most important \
content first (size, contrast, whitespace, ordering), or does everything \
compete for attention equally?
2. cta_visibility — Looking at the above-the-fold viewport specifically: is \
the primary call-to-action immediately visible and visually distinct \
(color, size, placement), or is it buried, missing, or easy to miss?
3. layout_issues — Any broken, overlapping, misaligned, cut-off, or \
awkwardly-spaced elements visible in either screenshot?
4. contrast_problems — Any text or interactive elements with insufficient \
color contrast against their background, making them hard to read?

For every strength, weakness, and recommendation, also rate your own \
confidence in that specific observation as "high", "medium", or "low":
- high — an objective, clearly visible fact in the screenshots (e.g. a \
button is cut off, text overlaps an image); not a matter of taste.
- medium — a reasonable design judgment based on what's visible, but one \
where context you can't see (brand guidelines, A/B test data) could justify \
the choice.
- low — a subjective aesthetic opinion or a borderline call where another \
reviewer could reasonably disagree.

Respond with ONLY valid JSON (no markdown code fences, no commentary before \
or after) matching exactly this schema:

{{
  "strengths": [
    {{"dimension": "<one of visual_hierarchy|cta_visibility|layout_issues|contrast_problems>", "point": "<specific, evidence-based observation>", "confidence": "<high|medium|low>"}}
  ],
  "weaknesses": [
    {{"dimension": "<same four options>", "point": "<specific, evidence-based observation>", "confidence": "<high|medium|low>"}}
  ],
  "recommendations": [
    {{"dimension": "<same four options>", "point": "<specific, actionable fix>", "confidence": "<high|medium|low>"}}
  ],
  "score": <integer 0-100, your holistic assessment of overall visual design quality>
}}

Cover as many of the four dimensions as the screenshots support; it is fine \
to omit a dimension entirely if there is nothing notable to say about it, \
but do not fabricate observations about elements that aren't visible. The \
first image attached is the above-the-fold viewport; the second is the full \
page."""


def build_visual_prompt(url: str) -> str:
    """Render the visual-analysis user prompt for a single page's screenshots."""
    return VISUAL_ANALYSIS_USER_TEMPLATE.format(url=url)
