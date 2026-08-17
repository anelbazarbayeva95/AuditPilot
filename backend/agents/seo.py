"""
SEO agent (Milestone 3).

Runs a set of static, rule-based SEO checks against scraped page data (no
Gemini yet — that layer turns findings into richer recommendations later).
Checks implemented:

  - page <title> exists
  - meta description exists
  - single <h1> (flags both zero and multiple)
  - required Open Graph tags present (og:title, og:description, og:image)
  - image alt text present (alt text also affects image-search SEO)

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
    AuditCategory,
    CategoryCoverage,
    CategoryResult,
    ConfidenceLevel,
    CoverageMethod,
    DetectionMethod,
    Recommendation,
    ScrapedPageData,
    SEOCheck,
    SEOFinding,
    SEOResult,
    Severity,
)

# Open Graph tags every page should have for clean link previews / social sharing.
_REQUIRED_OG_TAGS = ("og:title", "og:description", "og:image")

# What these six checks do not look at. Without this list a clean run reads as
# "SEO is fine", which six on-page checks cannot establish — technical SEO,
# indexability, and structured data are all untested here.
SEO_NOT_COVERED = [
    "Canonical URL and duplicate-content signals",
    "robots.txt and meta robots directives",
    "HTTP status codes and redirect chains",
    "XML sitemap presence and validity",
    "Structured data / schema.org markup",
    "Indexability and crawl budget",
    "Internal linking and anchor text",
    "Mobile rendering and viewport configuration",
    "Title and meta-description length limits",
    "Page speed as a ranking signal (see Performance)",
]


class SEOAgent(BaseAgent):
    category = AuditCategory.SEO

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

    def run_checks(self, page_data: ScrapedPageData) -> SEOResult:
        """Run all SEO checks against `page_data` and return {score, findings}."""
        findings: list[SEOFinding] = []

        findings.extend(self._check_title_exists(page_data))
        findings.extend(self._check_meta_description_exists(page_data))
        findings.extend(self._check_single_h1(page_data))
        findings.extend(self._check_open_graph_tags(page_data))
        findings.extend(self._check_image_alt_text(page_data))

        score, _ = score_with_explanation(findings)
        return SEOResult(score=score, findings=findings)

    # -- individual checks --------------------------------------------------

    @staticmethod
    def _check_title_exists(page_data: ScrapedPageData) -> list[SEOFinding]:
        if page_data.title and page_data.title.strip():
            return []
        return [
            SEOFinding(
                check=SEOCheck.MISSING_TITLE,
                severity=Severity.HIGH,
                message="Page is missing a <title> element (or it is empty).",
            )
        ]

    @staticmethod
    def _check_meta_description_exists(page_data: ScrapedPageData) -> list[SEOFinding]:
        if page_data.meta_description and page_data.meta_description.strip():
            return []
        return [
            SEOFinding(
                check=SEOCheck.MISSING_META_DESCRIPTION,
                severity=Severity.HIGH,
                message="Page is missing a meta description (or it is empty).",
            )
        ]

    @staticmethod
    def _check_single_h1(page_data: ScrapedPageData) -> list[SEOFinding]:
        count = len(page_data.h1_tags)
        if count == 0:
            return [
                SEOFinding(
                    check=SEOCheck.MISSING_H1,
                    severity=Severity.MEDIUM,
                    message="Page has no <h1> tag; search engines use it to understand the page topic.",
                )
            ]
        if count > 1:
            headings = [h for h in (normalize_page_text(t) for t in page_data.h1_tags) if h]
            preview = _h1_preview(headings)
            return [
                SEOFinding(
                    check=SEOCheck.MULTIPLE_H1,
                    severity=Severity.MEDIUM,
                    message=f"Page has {count} <h1> tags{preview}; a single <h1> is recommended for SEO.",
                    context=", ".join(headings[:5]),
                )
            ]
        return []

    @staticmethod
    def _check_open_graph_tags(page_data: ScrapedPageData) -> list[SEOFinding]:
        present = {key.lower(): value for key, value in page_data.open_graph.items()}
        findings = []
        for tag in _REQUIRED_OG_TAGS:
            if not present.get(tag, "").strip():
                findings.append(
                    SEOFinding(
                        check=SEOCheck.MISSING_OPEN_GRAPH_TAGS,
                        severity=Severity.MEDIUM,
                        message=f"Missing Open Graph tag '{tag}' — affects link previews on social platforms.",
                        context=tag,
                    )
                )
        return findings

    @staticmethod
    def _check_image_alt_text(page_data: ScrapedPageData) -> list[SEOFinding]:
        findings = []
        for image in page_data.images:
            # `alt is None` means the attribute is absent entirely. `alt == ""`
            # is a valid, intentional marker for decorative images and is not
            # flagged (mirrors the AccessibilityAgent's rule).
            if image.alt is None:
                findings.append(
                    SEOFinding(
                        check=SEOCheck.MISSING_IMAGE_ALT_TEXT,
                        severity=Severity.LOW,
                        message=f"Image '{image.src}' is missing alt text, which also feeds image search.",
                        context=image.src,
                        selector=image.selector,
                        section=image.section,
                    )
                )
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _h1_preview(h1_tags: list[str]) -> str:
    """' (e.g. 'A', 'B')' suffix naming the actual duplicate <h1> texts, so
    the finding says what those headings are rather than just how many there
    are. Empty string if there's nothing usable to preview."""
    preview = [tag for tag in h1_tags[:3] if tag.strip()]
    if not preview:
        return ""
    quoted = ", ".join(f"'{tag}'" for tag in preview)
    return f" (e.g. {quoted})"


def coverage() -> CategoryCoverage:
    """The on-page checks this agent runs, and the SEO surface it doesn't reach."""
    return CategoryCoverage(
        checks_run=[humanize(check) for check in SEOCheck],
        checks_not_covered=list(SEO_NOT_COVERED),
        method=CoverageMethod.AUTOMATED,
        notes=(
            "On-page checks against the rendered DOM of a single URL. Technical SEO (crawling, "
            "indexing, structured data) is out of scope for this run."
        ),
    )


def _summarize(result: SEOResult) -> str:
    checks = len(SEOCheck)
    if not result.findings:
        # "No SEO issues detected" is a claim six on-page checks can't support.
        # Say exactly what was tested instead, and point at what wasn't.
        return (
            f"No issues found across the {pluralize(checks, 'on-page check')} performed. "
            f"{pluralize(len(SEO_NOT_COVERED), 'further SEO area')} were not tested — "
            "see Methodology."
        )
    return (
        f"{pluralize(len(result.findings), 'SEO issue')} found across the "
        f"{pluralize(checks, 'on-page check')} performed."
    )


def _finding_to_recommendation(finding: SEOFinding) -> Recommendation:
    return prioritize(
        Recommendation(
            title=humanize(finding.check),
            description=finding.message,
            severity=finding.severity,
            category=AuditCategory.SEO,
            context=finding.context,
            selector=finding.selector,
            section=finding.section,
            ai_suggestion=finding.ai_suggestion,
            rule_id=finding.check.value,
            detection=DetectionMethod.AUTOMATED,
            confidence=ConfidenceLevel.HIGH,
        )
    )


def _coerce_page_data(page_data: Union[ScrapedPageData, dict, None]) -> ScrapedPageData:
    if isinstance(page_data, ScrapedPageData):
        return page_data
    if isinstance(page_data, dict):
        return ScrapedPageData(**page_data)
    raise ValueError("SEOAgent requires context['page_data'] (ScrapedPageData or dict)")
