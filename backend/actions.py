"""
Turns findings into an implementation plan.

A findings list and a plan are different documents. The findings list is
organized by *how the audit is structured* — one category per agent — but the
work isn't: adding an alt attribute to the hero image resolves an accessibility
finding and an SEO finding at once, and listing it twice makes one edit look
like two tickets. Worse, it makes the audit look like it doesn't understand its
own output.

So the plan is built by consolidating on the *fix*, not the finding:

- Findings whose remedy is the same edit collapse into one action, which names
  every category it benefits and how many findings it closes.
- Outcome metrics never become actions. "Lighthouse performance score is
  25/100" is a symptom of the render-blocking JavaScript below it; putting
  "improve the Lighthouse score" on a work list tells nobody what to do. The
  score is the KPI you re-measure afterwards, and the concrete interventions —
  named files, measured savings — are the work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from labels import humanize, pluralize
from models.schemas import (
    ActionItem,
    CategoryResult,
    ConfidenceLevel,
    DetectionMethod,
    EffortLevel,
    ImpactLevel,
    Recommendation,
    Severity,
    TimingBand,
)

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}
_TIMING_RANK = {TimingBand.IMMEDIATE: 0, TimingBand.NEXT_SPRINT: 1, TimingBand.BACKLOG: 2}
_IMPACT_RANK = {ImpactLevel.HIGH: 0, ImpactLevel.MEDIUM: 1, ImpactLevel.LOW: 2}
_EFFORT_RANK = {EffortLevel.QUICK: 0, EffortLevel.MODERATE: 1, EffortLevel.INVOLVED: 2}


@dataclass(frozen=True)
class _ActionSpec:
    """The canonical fix a set of rules all point at."""

    key: str
    title: str
    description: str
    standard: Optional[str] = None


# Rules that describe the same edit, keyed to the one action that resolves
# them. Anything not listed here becomes its own action keyed by rule id, so a
# new check is never silently merged into an unrelated fix.
_ACTION_BY_RULE: dict[str, _ActionSpec] = {}


def _register(spec: _ActionSpec, *rule_ids: str) -> None:
    for rule_id in rule_ids:
        _ACTION_BY_RULE[rule_id] = spec


_register(
    _ActionSpec(
        key="alt-text",
        title="Add alternative text to images",
        description=(
            "Give each flagged image a descriptive alt attribute, or alt=\"\" if it is purely "
            "decorative. One edit per image closes both the accessibility barrier and the "
            "image-search gap."
        ),
        standard="WCAG 1.1.1 — Non-text Content (Level A)",
    ),
    "missing_alt_text",
    "missing_image_alt_text",
)
_register(
    _ActionSpec(
        key="page-title",
        title="Add a page title",
        description=(
            "Add a unique, descriptive <title>. It names the page for screen reader users, "
            "browser tabs, search results, and shared links."
        ),
        standard="WCAG 2.4.2 — Page Titled (Level A)",
    ),
    "missing_page_title",
    "missing_title",
)
_register(
    _ActionSpec(
        key="heading-structure",
        title="Fix the page heading structure",
        description=(
            "Give the page exactly one <h1> naming its main topic and demote the rest, so "
            "assistive technology and search engines get one clear signal."
        ),
        standard="WCAG 1.3.1 — Info and Relationships (Level A)",
    ),
    "multiple_h1",
    "missing_h1",
)


def build_action_plan(
    categories: dict[str, CategoryResult], limit: int = 10
) -> tuple[list[ActionItem], list[str]]:
    """Consolidate findings into ranked actions.

    Returns the actions plus the KPI notes — the outcome metrics deliberately
    kept out of the plan, so their absence reads as a decision rather than an
    omission.
    """
    actions: dict[str, ActionItem] = {}
    kpis: list[str] = []

    for name, result in categories.items():
        if result is None:
            continue
        for rec in result.recommendations:
            if _is_outcome_metric(rec):
                kpis.append(_kpi_note(rec, result))
                continue
            _merge(actions, rec, name)

    # Performance work comes from the measured opportunities rather than from
    # the threshold findings: "Eliminate render-blocking resources: main.css,
    # vendor.js (~1240 ms)" is a task, where "Slow LCP" is a symptom.
    performance = categories.get("performance")
    if performance is not None:
        for action in _performance_opportunity_actions(performance):
            existing = actions.get(action.key)
            if existing is None:
                actions[action.key] = action

    ordered = sorted(actions.values(), key=_sort_key)
    return ordered[:limit], kpis


def _is_outcome_metric(rec: Recommendation) -> bool:
    """True for findings that report a score rather than a fixable defect."""
    return rec.rule_id == "low_performance_score"


def _kpi_note(rec: Recommendation, result: CategoryResult) -> str:
    measured = rec.evidence.measured_value if rec.evidence else None
    value = measured or (f"{result.score:.0f}/100" if result.score is not None else "not measured")
    return (
        f"Lighthouse performance score ({value}) is the measure of success for the performance "
        "actions below, not a task in itself — re-run the audit to confirm it moves."
    )


def _merge(actions: dict[str, ActionItem], rec: Recommendation, category: str) -> None:
    spec = _ACTION_BY_RULE.get(rec.rule_id or "")
    key = spec.key if spec else (rec.rule_id or rec.title)

    existing = actions.get(key)
    if existing is None:
        actions[key] = ActionItem(
            key=key,
            title=spec.title if spec else rec.title,
            description=spec.description if spec else rec.description,
            categories=[category],
            rule_ids=[rec.rule_id] if rec.rule_id else [],
            findings_resolved=1,
            severity=rec.severity,
            impact=rec.impact,
            effort=rec.effort,
            timing=rec.timing,
            confidence=rec.confidence,
            detection=rec.detection,
            primary_standard=(spec.standard if spec else rec.wcag_criterion),
            validation=rec.validation,
            owner=rec.owner,
        )
        return

    existing.findings_resolved += 1
    if category not in existing.categories:
        existing.categories.append(category)
    if rec.rule_id and rec.rule_id not in existing.rule_ids:
        existing.rule_ids.append(rec.rule_id)
    # The merged action inherits the most urgent characterization of any
    # finding it closes — merging must never quietly downgrade a problem.
    if _SEVERITY_RANK.get(rec.severity, 9) < _SEVERITY_RANK.get(existing.severity, 9):
        existing.severity = rec.severity
    if _IMPACT_RANK.get(rec.impact, 9) < _IMPACT_RANK.get(existing.impact, 9):
        existing.impact = rec.impact
    if _TIMING_RANK.get(rec.timing, 9) < _TIMING_RANK.get(existing.timing, 9):
        existing.timing = rec.timing
    if _EFFORT_RANK.get(rec.effort, 9) > _EFFORT_RANK.get(existing.effort, 9):
        existing.effort = rec.effort  # the harder of the two is the real cost
    if existing.primary_standard is None:
        existing.primary_standard = rec.wcag_criterion
    if existing.validation is None:
        existing.validation = rec.validation


def _performance_opportunity_actions(performance: CategoryResult) -> list[ActionItem]:
    """Concrete interventions from Lighthouse's own measured opportunities."""
    raw = performance.raw_data or {}
    opportunities = raw.get("opportunities") or []

    items: list[ActionItem] = []
    for opportunity in opportunities[:4]:
        audit_id = opportunity.get("audit_id")
        if not audit_id:
            continue
        savings = []
        if opportunity.get("savings_ms"):
            savings.append(f"~{opportunity['savings_ms']:,.0f} ms")
        if opportunity.get("savings_bytes"):
            savings.append(f"{opportunity['savings_bytes'] / 1024:,.0f} KB")
        resources = opportunity.get("resources") or []

        # Lighthouse titles are imperative fragments with no terminal
        # punctuation ("Eliminate render-blocking resources"), so they need a
        # sentence break before the measured detail runs on into them.
        description = opportunity.get("title", audit_id).rstrip(".") + "."
        if resources:
            description += f" Measured on this page: {', '.join(resources[:3])}."
        if savings:
            description += f" Estimated saving {', '.join(savings)}."

        items.append(ActionItem(
            key=f"perf-{audit_id}",
            title=opportunity.get("title") or humanize(audit_id),
            description=description,
            categories=["performance"],
            rule_ids=[audit_id],
            findings_resolved=1,
            severity=Severity.HIGH if (opportunity.get("savings_ms") or 0) >= 500 else Severity.MEDIUM,
            impact=ImpactLevel.HIGH if (opportunity.get("savings_ms") or 0) >= 500 else ImpactLevel.MEDIUM,
            effort=EffortLevel.MODERATE,
            timing=TimingBand.NEXT_SPRINT,
            confidence=ConfidenceLevel.HIGH,
            detection=DetectionMethod.AUTOMATED,
            estimated_saving=", ".join(savings) or None,
            validation=(
                "Re-run Lighthouse under the conditions recorded in Methodology and confirm the "
                "opportunity's estimated saving is realized."
            ),
        ))
    return items


def _sort_key(action: ActionItem) -> tuple:
    return (
        _TIMING_RANK.get(action.timing, 3),
        _IMPACT_RANK.get(action.impact, 3),
        _SEVERITY_RANK.get(action.severity, 9),
        _EFFORT_RANK.get(action.effort, 3),
        -action.findings_resolved,
    )


def describe_benefit(action: ActionItem) -> str:
    """'Accessibility, SEO — closes 2 findings' for the plan's benefit column."""
    categories = ", ".join(humanize(c) for c in action.categories)
    if action.findings_resolved > 1:
        return f"{categories} — closes {pluralize(action.findings_resolved, 'finding')}"
    return categories
