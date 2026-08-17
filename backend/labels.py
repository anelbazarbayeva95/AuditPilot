"""
Human-readable labels and editorial helpers — the single source of truth for
how machine identifiers are written in anything a reader sees.

Agents key everything off enum values (`cta_quality`, `slow_lcp`,
`missing_alt_text`). Naive prettifying with `.replace("_", " ").title()`
produces "Cta Quality" and "Slow Lcp", which is exactly how a report announces
that nobody edited it. Acronyms and initialisms need a real map, not a
title-case call, so this module owns that map and every renderer goes through
it. Machine names still exist in the data and in the report's appendix — they
just never appear in prose.

`pluralize` exists for the same reason: "7 accessibility issue(s) found" is
unedited system output. Report copy should say "7 accessibility issues found"
and "1 accessibility issue found".
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Identifiers whose correct written form isn't reachable by title-casing —
# acronyms, initialisms, and product terms. Keyed by the raw enum value.
_LABEL_OVERRIDES: dict[str, str] = {
    # Copy dimensions
    "value_proposition_clarity": "Value proposition clarity",
    "readability": "Readability",
    "cta_quality": "CTA quality",
    "jargon": "Jargon",
    "trust_signals": "Trust signals",
    # Visual dimensions
    "visual_hierarchy": "Visual hierarchy",
    "cta_visibility": "CTA visibility",
    "layout_issues": "Layout issues",
    "contrast_problems": "Contrast problems",
    # Accessibility checks
    "missing_alt_text": "Missing alt text",
    "multiple_h1": "Multiple H1 headings",
    "empty_button": "Button with no accessible name",
    "missing_label": "Form field with no label",
    "missing_page_title": "Missing page title",
    # SEO checks
    "missing_title": "Missing page title",
    "missing_meta_description": "Missing meta description",
    "missing_h1": "Missing H1 heading",
    "missing_open_graph_tags": "Missing Open Graph tag",
    "missing_image_alt_text": "Missing image alt text",
    # Performance checks
    "low_performance_score": "Low Lighthouse performance score",
    "slow_lcp": "Slow LCP (Largest Contentful Paint)",
    "high_cls": "High CLS (Cumulative Layout Shift)",
    "slow_inp": "Slow INP (Interaction to Next Paint)",
    # Categories
    "accessibility": "Accessibility",
    "seo": "SEO",
    "performance": "Performance",
    "copy": "Copy",
    "visual": "Visual",
    # Enumerated report vocabulary
    "scored": "Scored",
    "insufficient_evidence": "Insufficient evidence",
    "not_run": "Not run",
    "automated": "Automated",
    "ai_generated": "AI-generated",
    "ai_assisted": "AI-assisted",
    "manual": "Manual",
    "immediate": "Immediate",
    "next_sprint": "Next sprint",
    "backlog": "Backlog",
    "quick": "Quick",
    "moderate": "Moderate",
    "involved": "Involved",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "critical": "Critical",
    "info": "Info",
}


def humanize(value: object) -> str:
    """Render a machine identifier the way a person would write it.

    Accepts a raw string or any Enum whose `.value` is one. Unknown
    identifiers fall back to sentence-cased words — never a crash, and never
    an invented label.
    """
    raw = getattr(value, "value", value)
    if raw is None:
        return ""
    text = str(raw)
    override = _LABEL_OVERRIDES.get(text.lower())
    if override:
        return override
    words = text.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else ""


def round_half_up(value: float) -> int:
    """Round the way a reader expects: 61.5 -> 62, 62.5 -> 63.

    Python's built-in `round` and `%.0f` both round halves to even, so 62.5
    would display as 62. Every score shown to a reader goes through this, so
    the report's own arithmetic always reproduces the number beside it.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


SCORE_BANDS: tuple[tuple[int, str], ...] = (
    (90, "Excellent"),
    (70, "Good"),
    (40, "Needs attention"),
    (0, "Critical"),
)


def score_band(score: float | None) -> str | None:
    """'61/100' says nothing on its own — this is what makes it interpretable.

    Bands are fixed and printed alongside the scale in the report, so the label
    is a stated convention rather than a private judgment.
    """
    if score is None:
        return None
    for floor, label in SCORE_BANDS:
        if score >= floor:
            return label
    return None


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """'1 issue' / '7 issues' — never '7 issue(s)'."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def format_report_datetime(moment) -> str:
    """'17 August 2026 at 04:09 UTC' — a date a client report can carry.

    Built without strftime's `%-d`/`%#d` day-padding flags, which are
    platform-specific and would render differently on Windows.
    """
    return f"{moment.day} {moment.strftime('%B %Y at %H:%M')} UTC"


def normalize_page_text(text: str | None) -> str | None:
    """Collapse whitespace in text lifted off a live page before quoting it back.

    Real pages wrap headings across elements and lines; quoting the raw string
    into prose is how "KYLIAN MBAPPÉ" and "MERCURIAL SUPERFLY" end up printed
    as one concatenated word. Returns None for text that is empty once
    normalized, so callers can treat it as absent rather than as an empty quote.
    """
    if text is None:
        return None
    collapsed = " ".join(text.split())
    return collapsed or None
