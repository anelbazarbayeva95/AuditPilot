"""
Prioritization metadata for findings — impact, effort, timing, and validation.

Severity alone can't drive an implementation plan: a high-severity issue on one
obscure element and a medium issue repeated across every template deserve
different treatment, and neither is distinguishable from a severity label. So
each finding also carries what it costs to fix, what it's worth fixing, when it
should be scheduled, and how to confirm the fix landed.

The maps are keyed by `rule_id` (the check enum's raw value), not by display
title — titles are editorial and change; rule ids are the stable contract with
the agents. Anything unmapped falls back to neutral defaults rather than an
invented estimate, and `timing` is always *derived* from impact/effort/
confidence rather than stored, so it can't drift out of sync with them.
"""

from __future__ import annotations

from typing import Optional

from models.schemas import (
    ConfidenceLevel,
    EffortLevel,
    ImpactLevel,
    Recommendation,
    Severity,
    TimingBand,
)

# What the issue costs the user or the business if left alone.
_IMPACT_BY_RULE: dict[str, ImpactLevel] = {
    "empty_button": ImpactLevel.HIGH,        # blocks keyboard/screen-reader users outright
    "missing_page_title": ImpactLevel.HIGH,
    "missing_title": ImpactLevel.HIGH,
    "missing_label": ImpactLevel.HIGH,       # form fields are conversion-critical
    "missing_alt_text": ImpactLevel.MEDIUM,
    "missing_image_alt_text": ImpactLevel.LOW,
    "multiple_h1": ImpactLevel.LOW,
    "missing_h1": ImpactLevel.MEDIUM,
    "missing_meta_description": ImpactLevel.MEDIUM,
    "missing_open_graph_tags": ImpactLevel.LOW,
    "low_performance_score": ImpactLevel.HIGH,
    "slow_lcp": ImpactLevel.HIGH,
    "high_cls": ImpactLevel.MEDIUM,
    "slow_inp": ImpactLevel.MEDIUM,
}

# How much work the fix is. "quick" means a content/attribute edit; "involved"
# means it needs engineering investigation or architectural change.
_EFFORT_BY_RULE: dict[str, EffortLevel] = {
    "empty_button": EffortLevel.QUICK,
    "missing_alt_text": EffortLevel.QUICK,
    "missing_image_alt_text": EffortLevel.QUICK,
    "missing_page_title": EffortLevel.QUICK,
    "missing_title": EffortLevel.QUICK,
    "missing_meta_description": EffortLevel.QUICK,
    "missing_open_graph_tags": EffortLevel.QUICK,
    "missing_label": EffortLevel.QUICK,
    "missing_h1": EffortLevel.MODERATE,
    "multiple_h1": EffortLevel.MODERATE,
    "high_cls": EffortLevel.MODERATE,
    "slow_lcp": EffortLevel.INVOLVED,
    "slow_inp": EffortLevel.INVOLVED,
    "low_performance_score": EffortLevel.INVOLVED,
}

# How a reader confirms the fix actually landed — the audit's own re-test is
# the baseline, but each of these names the specific observable that changes.
_VALIDATION_BY_RULE: dict[str, str] = {
    "empty_button": (
        "Inspect the element in the browser's accessibility pane: it should expose a non-empty "
        "name. Re-run this audit and confirm the finding is gone."
    ),
    "missing_alt_text": (
        "Confirm the <img> has an alt attribute describing its purpose (or alt=\"\" if it is "
        "genuinely decorative), then re-run this audit."
    ),
    "missing_image_alt_text": (
        "Confirm the <img> has a descriptive alt attribute, then re-run this audit."
    ),
    "missing_label": (
        "Confirm the field has a <label for>, a wrapping <label>, or an aria-label, then re-run "
        "this audit."
    ),
    "missing_page_title": "View the page source and confirm a non-empty <title>, then re-run this audit.",
    "missing_title": "View the page source and confirm a non-empty <title>, then re-run this audit.",
    "missing_meta_description": (
        "Confirm <meta name=\"description\"> is present and non-empty, then re-check how the page "
        "renders in a search result preview."
    ),
    "missing_h1": "Confirm the page has exactly one <h1> naming its main topic, then re-run this audit.",
    "multiple_h1": "Confirm only one <h1> remains and the others are demoted, then re-run this audit.",
    "missing_open_graph_tags": (
        "Re-share the URL on the target platform (or use its link-preview debugger) and confirm the "
        "preview renders."
    ),
    "slow_lcp": (
        "Re-run Lighthouse under the same conditions recorded in Methodology and confirm LCP "
        "improved against the 2500 ms threshold."
    ),
    "high_cls": (
        "Re-run Lighthouse under the same conditions recorded in Methodology and confirm CLS is at "
        "or below 0.1."
    ),
    "slow_inp": (
        "Re-run Lighthouse under the same conditions recorded in Methodology and confirm INP is at "
        "or below 200 ms."
    ),
    "low_performance_score": (
        "Re-run Lighthouse under the same conditions recorded in Methodology and compare the "
        "performance score and the named opportunities."
    ),
}

_SEVERITY_IMPACT_FALLBACK: dict[Severity, ImpactLevel] = {
    Severity.CRITICAL: ImpactLevel.HIGH,
    Severity.HIGH: ImpactLevel.HIGH,
    Severity.MEDIUM: ImpactLevel.MEDIUM,
    Severity.LOW: ImpactLevel.LOW,
    Severity.INFO: ImpactLevel.LOW,
}


def impact_for(rule_id: Optional[str], severity: Severity) -> ImpactLevel:
    """Mapped impact for a known rule, else derived from severity."""
    if rule_id and rule_id in _IMPACT_BY_RULE:
        return _IMPACT_BY_RULE[rule_id]
    return _SEVERITY_IMPACT_FALLBACK.get(severity, ImpactLevel.MEDIUM)


def effort_for(rule_id: Optional[str]) -> EffortLevel:
    """Mapped effort for a known rule, else the neutral middle tier."""
    if rule_id and rule_id in _EFFORT_BY_RULE:
        return _EFFORT_BY_RULE[rule_id]
    return EffortLevel.MODERATE


def validation_for(rule_id: Optional[str]) -> Optional[str]:
    """How to verify this specific fix. None when we have nothing specific to say."""
    return _VALIDATION_BY_RULE.get(rule_id or "")


def timing_for(
    impact: ImpactLevel,
    effort: EffortLevel,
    confidence: Optional[ConfidenceLevel] = None,
) -> TimingBand:
    """Derive when to schedule the fix.

    High impact that is cheap and well-evidenced is immediate work. High impact
    that needs real engineering, or that rests on a low-confidence observation,
    is planned rather than rushed. Low impact waits.
    """
    if impact is ImpactLevel.LOW:
        return TimingBand.BACKLOG
    if confidence is ConfidenceLevel.LOW:
        return TimingBand.NEXT_SPRINT
    if impact is ImpactLevel.HIGH and effort is not EffortLevel.INVOLVED:
        return TimingBand.IMMEDIATE
    return TimingBand.NEXT_SPRINT


def prioritize(recommendation: Recommendation) -> Recommendation:
    """Fill in impact/effort/timing/validation on a recommendation, in place.

    Only fills what isn't already set, so an agent that knows better about its
    own finding keeps the last word.
    """
    if recommendation.impact is None:
        recommendation.impact = impact_for(recommendation.rule_id, recommendation.severity)
    if recommendation.effort is None:
        recommendation.effort = effort_for(recommendation.rule_id)
    if recommendation.validation is None:
        recommendation.validation = validation_for(recommendation.rule_id)
    if recommendation.timing is None:
        recommendation.timing = timing_for(
            recommendation.impact, recommendation.effort, recommendation.confidence
        )
    return recommendation
