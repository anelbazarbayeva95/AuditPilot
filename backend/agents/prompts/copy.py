"""
Prompt templates for CopyAgent (Milestone 4).

Kept separate from agents/copy.py so the prompt wording can be iterated on
independently of the parsing/error-handling logic, and so future agents can
follow the same "prompts module + parsing module" split.
"""

from __future__ import annotations

from models.schemas import ScrapedPageData

COPY_ANALYSIS_SYSTEM_PROMPT = """\
You are a senior conversion copywriter and UX writer auditing a marketing \
website. You give specific, evidence-based feedback grounded only in the \
content provided — never invent claims about the page you weren't given."""

_MAX_LINK_TEXT_CHARS = 500

COPY_ANALYSIS_USER_TEMPLATE = """\
Analyze the on-page copy below across exactly these five dimensions:

1. value_proposition_clarity — Is it immediately clear what the product/service \
is, who it's for, and why it matters, from the title/headings/meta description alone?
2. readability — Is the copy concise and easy to scan, or dense/bloated with \
long sentences and walls of text?
3. cta_quality — Do buttons/CTAs use specific, action-oriented text (e.g. \
"Start your free trial") rather than generic text (e.g. "Submit", "Click here", "")?
4. jargon — Does the copy lean on unexplained technical/internal jargon or \
buzzwords instead of plain language?
5. trust_signals — Are there indicators of credibility (specific numbers, \
named customers, guarantees, certifications, testimonials) or is the copy \
generic and unsubstantiated?

PAGE DATA
Title: {title}
Meta description: {meta_description}
H1 headings: {h1_tags}
H2 headings: {h2_tags}
Button/CTA text: {button_texts}
Sample link text: {link_texts}

For every strength, weakness, and recommendation, also rate your own \
confidence in that specific observation as "high", "medium", or "low":
- high — directly and unambiguously supported by specific text you were \
given above (you could quote the exact words); not a matter of opinion.
- medium — a reasonable reading of the evidence provided, but somewhat \
subjective or inferred rather than directly quotable.
- low — a plausible judgment call or stylistic opinion where another \
reviewer could reasonably disagree, or where the page data gives limited \
signal either way.

Respond with ONLY valid JSON (no markdown code fences, no commentary before \
or after) matching exactly this schema:

{{
  "strengths": [
    {{"dimension": "<one of value_proposition_clarity|readability|cta_quality|jargon|trust_signals>", "point": "<specific, evidence-based observation>", "confidence": "<high|medium|low>"}}
  ],
  "weaknesses": [
    {{"dimension": "<same five options>", "point": "<specific, evidence-based observation>", "confidence": "<high|medium|low>"}}
  ],
  "recommendations": [
    {{"dimension": "<same five options>", "point": "<specific, actionable fix>", "confidence": "<high|medium|low>"}}
  ],
  "score": <integer 0-100, your holistic assessment of overall copy quality>
}}

Cover as many of the five dimensions as the page data supports; it is fine to \
omit a dimension entirely if there is nothing notable to say about it, but \
do not fabricate observations about content that isn't present above."""


def _join_or_placeholder(values: list[str], placeholder: str = "(none)") -> str:
    cleaned = [v.strip() for v in values if v and v.strip()]
    return ", ".join(cleaned) if cleaned else placeholder


def build_copy_prompt(page_data: ScrapedPageData) -> str:
    """Render the copy-analysis user prompt for a single scraped page."""
    button_texts = _join_or_placeholder([b.text for b in page_data.buttons])
    link_texts = _join_or_placeholder([link.text or "" for link in page_data.links])[:_MAX_LINK_TEXT_CHARS]

    return COPY_ANALYSIS_USER_TEMPLATE.format(
        title=page_data.title or "(missing)",
        meta_description=page_data.meta_description or "(missing)",
        h1_tags=_join_or_placeholder(page_data.h1_tags),
        h2_tags=_join_or_placeholder(page_data.h2_tags),
        button_texts=button_texts,
        link_texts=link_texts,
    )
