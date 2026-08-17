"""
Accessibility agent (Milestone 2 — first real agent).

Runs a set of static, rule-based accessibility checks against scraped page
data (no Gemini yet — that layer is added later to turn findings into
richer, natural-language recommendations). Checks implemented:

  - missing alt text on <img> elements
  - multiple <h1> tags on one page
  - buttons with no accessible name (empty buttons)
  - form fields with no associated label
  - missing/empty page <title>

`run_checks` is the pure, synchronous core (easy to unit test in isolation).
`analyze` is the async BaseAgent-interface entrypoint the orchestrator calls;
it wraps `run_checks` output into a CategoryResult.
"""

from __future__ import annotations

from typing import Any, Union

from agents.base import BaseAgent
from agents.prioritization import prioritize
from agents.scoring import score_with_explanation
from labels import humanize, normalize_page_text, pluralize
from models.schemas import (
    AccessibilityCheck,
    AccessibilityFinding,
    AccessibilityResult,
    AuditCategory,
    ButtonData,
    CategoryCoverage,
    CategoryResult,
    ConfidenceLevel,
    CoverageMethod,
    DetectionMethod,
    Evidence,
    Recommendation,
    ScrapedPageData,
    Severity,
)

# Each rule's WCAG 2.2 success criterion. This lives in the backend rather than
# in frontend presentation code so the PDF, the API, and the UI all cite the
# same criterion — a report that evaluates accessibility has to be able to say
# which standard it is measuring against, in every output it produces.
WCAG_BY_CHECK: dict[AccessibilityCheck, str] = {
    AccessibilityCheck.MISSING_ALT_TEXT: "WCAG 1.1.1 — Non-text Content (Level A)",
    AccessibilityCheck.MULTIPLE_H1: "WCAG 1.3.1 — Info and Relationships (Level A)",
    AccessibilityCheck.EMPTY_BUTTON: "WCAG 4.1.2 — Name, Role, Value (Level A)",
    AccessibilityCheck.MISSING_LABEL: "WCAG 3.3.2 — Labels or Instructions (Level A)",
    AccessibilityCheck.MISSING_PAGE_TITLE: "WCAG 2.4.2 — Page Titled (Level A)",
}

# What these five rules do *not* look at. Publishing this is the difference
# between "70/100, accessibility assessed" and "70/100 across five automated
# checks, with these areas untested" — only the second is a claim the audit can
# actually support.
ACCESSIBILITY_NOT_COVERED = [
    "Color contrast ratios",
    "Keyboard focus order and focus visibility",
    "Keyboard traps and skip links",
    "ARIA role/state validity",
    "Reading and tab order",
    "Motion, animation, and time limits",
    "Media captions and transcripts",
    "Zoom, reflow, and text spacing",
]


class AccessibilityAgent(BaseAgent):
    category = AuditCategory.ACCESSIBILITY

    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        """BaseAgent entrypoint used by the orchestrator.

        Expects `context["page_data"]` to be a ScrapedPageData instance or an
        equivalent dict (e.g. from `orchestrator._scrape`).
        """
        page_data = _coerce_page_data(context.get("page_data"))
        result = self.run_checks(page_data)
        _, explanation = score_with_explanation(result.findings)

        return CategoryResult(
            category=self.category,
            score=result.score,
            score_explanation=explanation,
            coverage=coverage(),
            summary=_summarize(result),
            recommendations=[_finding_to_recommendation(f) for f in result.findings],
            raw_data=result.model_dump(),
        )

    def run_checks(self, page_data: ScrapedPageData) -> AccessibilityResult:
        """Run all accessibility checks against `page_data` and return {score, findings}."""
        findings: list[AccessibilityFinding] = []

        findings.extend(self._check_missing_page_title(page_data))
        findings.extend(self._check_multiple_h1(page_data))
        findings.extend(self._check_missing_alt_text(page_data))
        findings.extend(self._check_empty_buttons(page_data))
        findings.extend(self._check_missing_labels(page_data))

        findings = _dedupe(findings)
        score, _ = score_with_explanation(findings)
        return AccessibilityResult(score=score, findings=findings)

    # -- individual checks --------------------------------------------------

    @staticmethod
    def _check_missing_page_title(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        if page_data.title and page_data.title.strip():
            return []
        return [
            AccessibilityFinding(
                check=AccessibilityCheck.MISSING_PAGE_TITLE,
                severity=Severity.HIGH,
                message="Page is missing a <title> element (or it is empty).",
                wcag_criterion=WCAG_BY_CHECK[AccessibilityCheck.MISSING_PAGE_TITLE],
            )
        ]

    @staticmethod
    def _check_multiple_h1(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        headings = [h for h in (normalize_page_text(t) for t in page_data.h1_tags) if h]
        count = len(page_data.h1_tags)
        if count <= 1:
            return []
        preview = _h1_preview(headings)
        return [
            AccessibilityFinding(
                check=AccessibilityCheck.MULTIPLE_H1,
                severity=Severity.MEDIUM,
                message=(
                    f"Page has {count} <h1> tags{preview}; screen reader users rely on a "
                    "single <h1> to understand the page's main topic."
                ),
                context=", ".join(headings[:5]),
                wcag_criterion=WCAG_BY_CHECK[AccessibilityCheck.MULTIPLE_H1],
            )
        ]

    @staticmethod
    def _check_missing_alt_text(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        findings = []
        for image in page_data.images:
            # `alt is None` means the attribute is absent entirely (bad).
            # `alt == ""` means alt="" is present, which is valid for
            # intentionally decorative images, so it is not flagged.
            if image.alt is None:
                findings.append(
                    AccessibilityFinding(
                        check=AccessibilityCheck.MISSING_ALT_TEXT,
                        severity=Severity.HIGH,
                        message=f"Image '{image.src}' is missing an alt attribute.",
                        context=image.src,
                        selector=image.selector,
                        section=image.section,
                        wcag_criterion=WCAG_BY_CHECK[AccessibilityCheck.MISSING_ALT_TEXT],
                        dom_excerpt=image.dom_excerpt,
                    )
                )
        return findings

    @staticmethod
    def _check_empty_buttons(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        findings = []
        for index, button in enumerate(page_data.buttons):
            if not _has_no_accessible_name(button):
                continue
            # Prefer the scraper's real computed CSS selector (handles
            # nesting properly); _describe_button is only a fallback for
            # the rare case a selector couldn't be computed.
            locator = button.selector or _describe_button(button, index)
            findings.append(
                AccessibilityFinding(
                    check=AccessibilityCheck.EMPTY_BUTTON,
                    severity=Severity.HIGH,
                    message=f"The button '{locator}' has no accessible name.",
                    context=locator,
                    selector=button.selector,
                    section=button.section,
                    wcag_criterion=WCAG_BY_CHECK[AccessibilityCheck.EMPTY_BUTTON],
                    dom_excerpt=button.dom_excerpt,
                    accessible_name_computation=_ACCESSIBLE_NAME_TRACE,
                )
            )
        return findings

    @staticmethod
    def _check_missing_labels(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        findings = []
        for field in page_data.inputs:
            if field.has_label:
                continue
            identifier = field.name or field.id or field.type
            findings.append(
                AccessibilityFinding(
                    check=AccessibilityCheck.MISSING_LABEL,
                    severity=Severity.MEDIUM,
                    message=f"Form field '{identifier}' ({field.type}) has no associated label.",
                    context=identifier,
                    wcag_criterion=WCAG_BY_CHECK[AccessibilityCheck.MISSING_LABEL],
                    accessible_name_computation=(
                        "no <label for>, no wrapping <label>, no aria-label, no aria-labelledby "
                        "-> accessible name is empty"
                    ),
                )
            )
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The name-resolution order this finding rules out, spelled out for a reader
# who has to fix it. Only emitted for buttons the scraper actually evaluated
# against all of these sources.
_ACCESSIBLE_NAME_TRACE = (
    "no aria-labelledby, no aria-label, no text content, no value, no title "
    "-> accessible name is empty"
)


def _has_no_accessible_name(button: ButtonData) -> bool:
    """True when the button exposes no accessible name at all.

    Prefers the scraper's `accessible_name`, which resolves the real precedence
    order (aria-labelledby > aria-label > content > value > title). Falls back
    to `text` for payloads captured before that field existed — `None` there
    means "not computed", which is not the same as "empty".
    """
    if button.accessible_name is not None:
        return not button.accessible_name.strip()
    return not button.text or not button.text.strip()


def coverage() -> CategoryCoverage:
    """The checks this agent runs, and the ones it explicitly does not."""
    return CategoryCoverage(
        checks_run=[humanize(check) for check in AccessibilityCheck],
        checks_not_covered=list(ACCESSIBILITY_NOT_COVERED),
        method=CoverageMethod.AUTOMATED,
        notes=(
            "Automated static checks against the rendered DOM of a single URL. No manual "
            "verification pass, no assistive-technology testing."
        ),
    )


def _dedupe(findings: list[AccessibilityFinding]) -> list[AccessibilityFinding]:
    """Drop findings that point at the same element with the same check.

    Distinct elements are distinct findings and are all kept — eight empty
    buttons are eight real problems, not one. This only removes genuine
    repeats, which can happen when a page nests one matched element inside
    another (a [role="button"] wrapping a <button>) so both resolve to the same
    computed selector. Findings with no selector are element-independent
    (page-level checks) and are never merged on identity alone.
    """
    seen: set[tuple[object, str]] = set()
    deduped: list[AccessibilityFinding] = []
    for finding in findings:
        if finding.selector:
            key = (finding.check, finding.selector)
            if key in seen:
                continue
            seen.add(key)
        deduped.append(finding)
    return deduped


def _describe_button(button: ButtonData, index: int) -> str:
    """Best real, non-fabricated identifier for a button with no accessible
    name. Prefers a real `id`/`class` attribute actually captured off the
    live DOM (see scraper.py) — never invents a selector — and only falls
    back to the button's position on the page when neither is present."""
    if button.id:
        return f"#{button.id}"
    if button.class_name:
        first_class = button.class_name.split()[0]
        return f".{first_class}"
    kind = button.button_type or "button"
    return f"{kind} #{index + 1} on the page"


def _h1_preview(h1_tags: list[str]) -> str:
    """' (e.g. \\'A\\', \\'B\\')' suffix naming the actual duplicate <h1> texts,
    so the finding says what those headings are rather than just how many
    there are. Empty string if there's nothing usable to preview."""
    preview = [tag for tag in h1_tags[:3] if tag.strip()]
    if not preview:
        return ""
    quoted = ", ".join(f"'{tag}'" for tag in preview)
    return f" (e.g. {quoted})"


def _summarize(result: AccessibilityResult) -> str:
    checks = len(AccessibilityCheck)
    if not result.findings:
        return (
            f"No issues found across the {pluralize(checks, 'automated check')} performed. "
            "See Methodology for what these checks do not cover."
        )
    return (
        f"{pluralize(len(result.findings), 'accessibility issue')} found across the "
        f"{pluralize(checks, 'automated check')} performed."
    )


def _finding_to_recommendation(finding: AccessibilityFinding) -> Recommendation:
    evidence = None
    if finding.dom_excerpt or finding.accessible_name_computation:
        evidence = Evidence(
            dom_excerpt=finding.dom_excerpt,
            accessible_name_computation=finding.accessible_name_computation,
        )
    return prioritize(
        Recommendation(
            title=humanize(finding.check),
            description=finding.message,
            severity=finding.severity,
            category=AuditCategory.ACCESSIBILITY,
            context=finding.context,
            selector=finding.selector,
            section=finding.section,
            ai_suggestion=finding.ai_suggestion,
            wcag_criterion=finding.wcag_criterion,
            rule_id=finding.check.value,
            # These are deterministic checks against the rendered DOM, not
            # judgment calls — the report needs to be able to say so.
            detection=DetectionMethod.AUTOMATED,
            confidence=ConfidenceLevel.HIGH,
            evidence=evidence,
        )
    )


def _coerce_page_data(page_data: Union[ScrapedPageData, dict, None]) -> ScrapedPageData:
    if isinstance(page_data, ScrapedPageData):
        return page_data
    if isinstance(page_data, dict):
        return ScrapedPageData(**page_data)
    raise ValueError("AccessibilityAgent requires context['page_data'] (ScrapedPageData or dict)")
