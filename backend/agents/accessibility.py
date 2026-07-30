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
from agents.scoring import score_from_findings
from models.schemas import (
    AccessibilityCheck,
    AccessibilityFinding,
    AccessibilityResult,
    AuditCategory,
    ButtonData,
    CategoryResult,
    Recommendation,
    ScrapedPageData,
    Severity,
)


class AccessibilityAgent(BaseAgent):
    category = AuditCategory.ACCESSIBILITY

    async def analyze(self, url: str, context: dict[str, Any]) -> CategoryResult:
        """BaseAgent entrypoint used by the orchestrator.

        Expects `context["page_data"]` to be a ScrapedPageData instance or an
        equivalent dict (e.g. from `orchestrator._scrape`).
        """
        page_data = _coerce_page_data(context.get("page_data"))
        result = self.run_checks(page_data)

        return CategoryResult(
            category=self.category,
            score=result.score,
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

        score = score_from_findings(findings)
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
            )
        ]

    @staticmethod
    def _check_multiple_h1(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        count = len(page_data.h1_tags)
        if count <= 1:
            return []
        preview = _h1_preview(page_data.h1_tags)
        return [
            AccessibilityFinding(
                check=AccessibilityCheck.MULTIPLE_H1,
                severity=Severity.MEDIUM,
                message=(
                    f"Page has {count} <h1> tags{preview}; screen reader users rely on a "
                    "single <h1> to understand the page's main topic."
                ),
                context=", ".join(page_data.h1_tags[:5]),
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
                    )
                )
        return findings

    @staticmethod
    def _check_empty_buttons(page_data: ScrapedPageData) -> list[AccessibilityFinding]:
        findings = []
        for index, button in enumerate(page_data.buttons):
            if not button.text or not button.text.strip():
                # Prefer the scraper's real computed CSS selector (handles
                # nesting properly); _describe_button is only a fallback for
                # the rare case a selector couldn't be computed.
                locator = button.selector or _describe_button(button, index)
                findings.append(
                    AccessibilityFinding(
                        check=AccessibilityCheck.EMPTY_BUTTON,
                        severity=Severity.HIGH,
                        message=f"The button '{locator}' has no accessible text (no label, value, or aria-label).",
                        context=locator,
                        selector=button.selector,
                        section=button.section,
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
                )
            )
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    if not result.findings:
        return "No accessibility issues detected."
    return f"{len(result.findings)} accessibility issue(s) found. Score: {result.score:.0f}/100."


def _finding_to_recommendation(finding: AccessibilityFinding) -> Recommendation:
    return Recommendation(
        title=finding.check.value.replace("_", " ").title(),
        description=finding.message,
        severity=finding.severity,
        category=AuditCategory.ACCESSIBILITY,
        context=finding.context,
        selector=finding.selector,
        section=finding.section,
        ai_suggestion=finding.ai_suggestion,
    )


def _coerce_page_data(page_data: Union[ScrapedPageData, dict, None]) -> ScrapedPageData:
    if isinstance(page_data, ScrapedPageData):
        return page_data
    if isinstance(page_data, dict):
        return ScrapedPageData(**page_data)
    raise ValueError("AccessibilityAgent requires context['page_data'] (ScrapedPageData or dict)")
