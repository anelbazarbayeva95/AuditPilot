"""
Unit tests for AccessibilityAgent (Milestone 2).

Covers each rule in isolation (missing alt text, multiple h1, empty buttons,
missing labels, missing page title), a clean page with no findings, the
per-check deduction cap, and the async `analyze()` orchestrator entrypoint.
"""

from __future__ import annotations

import pytest

from agents.accessibility import AccessibilityAgent
from models.schemas import (
    AccessibilityCheck,
    AuditCategory,
    ButtonData,
    ImageData,
    InputData,
    ConfidenceLevel,
    CoverageMethod,
    DetectionMethod,
    ScrapedPageData,
    Severity,
)


def make_page(**overrides) -> ScrapedPageData:
    """A clean, fully-accessible page; override individual fields per test."""
    defaults = dict(
        url="https://example.com",
        title="Example Domain",
        meta_description="An example page.",
        h1_tags=["Welcome"],
        h2_tags=[],
        images=[ImageData(src="logo.png", alt="Company logo")],
        buttons=[ButtonData(text="Submit")],
        links=[],
        inputs=[InputData(type="text", id="email", name="email", has_label=True)],
    )
    defaults.update(overrides)
    return ScrapedPageData(**defaults)


@pytest.fixture
def agent() -> AccessibilityAgent:
    return AccessibilityAgent()


class TestCleanPage:
    def test_clean_page_has_no_findings(self, agent):
        result = agent.run_checks(make_page())
        assert result.findings == []

    def test_clean_page_scores_100(self, agent):
        result = agent.run_checks(make_page())
        assert result.score == 100.0


class TestMissingPageTitle:
    @pytest.mark.parametrize("title", [None, "", "   "])
    def test_flags_missing_or_empty_title(self, agent, title):
        result = agent.run_checks(make_page(title=title))
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MISSING_PAGE_TITLE in checks

    def test_present_title_not_flagged(self, agent):
        result = agent.run_checks(make_page(title="Real Title"))
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MISSING_PAGE_TITLE not in checks

    def test_deducts_expected_points(self, agent):
        result = agent.run_checks(make_page(title=None))
        assert result.score == 90.0  # 100 - HIGH(10)


class TestMultipleH1:
    def test_single_h1_not_flagged(self, agent):
        result = agent.run_checks(make_page(h1_tags=["Only One"]))
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MULTIPLE_H1 not in checks

    def test_zero_h1_not_flagged_by_this_check(self, agent):
        # This agent only checks for *multiple* h1s, not zero — a missing
        # h1 is out of scope for Milestone 2.
        result = agent.run_checks(make_page(h1_tags=[]))
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MULTIPLE_H1 not in checks

    def test_multiple_h1_flagged(self, agent):
        result = agent.run_checks(make_page(h1_tags=["First", "Second"]))
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MULTIPLE_H1]
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM

    def test_multiple_h1_message_names_the_actual_headings(self, agent):
        # The message should say *what* the duplicate headings are, not just
        # how many there are — otherwise every "Multiple H1" finding across
        # every audit reads identically.
        result = agent.run_checks(make_page(h1_tags=["Shop Now", "Welcome Back"]))
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MULTIPLE_H1]
        assert "Shop Now" in matches[0].message
        assert "Welcome Back" in matches[0].message

    def test_deducts_expected_points(self, agent):
        result = agent.run_checks(make_page(h1_tags=["First", "Second"]))
        assert result.score == 95.0  # 100 - MEDIUM(5)


class TestMissingAltText:
    def test_missing_alt_attribute_flagged(self, agent):
        result = agent.run_checks(
            make_page(images=[ImageData(src="hero.png", alt=None)])
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MISSING_ALT_TEXT]
        assert len(matches) == 1
        assert matches[0].context == "hero.png"
        assert matches[0].severity == Severity.HIGH

    def test_empty_alt_is_decorative_and_not_flagged(self, agent):
        # alt="" is a valid, intentional marker for decorative images.
        result = agent.run_checks(
            make_page(images=[ImageData(src="divider.png", alt="")])
        )
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MISSING_ALT_TEXT not in checks

    def test_present_alt_not_flagged(self, agent):
        result = agent.run_checks(
            make_page(images=[ImageData(src="hero.png", alt="Hero banner")])
        )
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MISSING_ALT_TEXT not in checks

    def test_multiple_missing_alt_images_each_flagged(self, agent):
        result = agent.run_checks(
            make_page(
                images=[
                    ImageData(src="a.png", alt=None),
                    ImageData(src="b.png", alt=None),
                ]
            )
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MISSING_ALT_TEXT]
        assert len(matches) == 2


class TestEmptyButtons:
    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_button_flagged(self, agent, text):
        result = agent.run_checks(make_page(buttons=[ButtonData(text=text)]))
        matches = [f for f in result.findings if f.check == AccessibilityCheck.EMPTY_BUTTON]
        assert len(matches) == 1
        assert matches[0].severity == Severity.HIGH

    def test_labeled_button_not_flagged(self, agent):
        result = agent.run_checks(make_page(buttons=[ButtonData(text="Buy now")]))
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.EMPTY_BUTTON not in checks

    def test_empty_button_with_id_uses_real_id_as_locator(self, agent):
        # A real id captured off the page is the best possible locator —
        # never a fabricated selector, just the actual attribute.
        result = agent.run_checks(
            make_page(buttons=[ButtonData(text="", id="newsletter-submit")])
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.EMPTY_BUTTON]
        assert matches[0].context == "#newsletter-submit"
        assert "#newsletter-submit" in matches[0].message

    def test_empty_button_with_class_but_no_id_uses_class(self, agent):
        result = agent.run_checks(
            make_page(buttons=[ButtonData(text="", class_name="icon-btn ghost")])
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.EMPTY_BUTTON]
        assert matches[0].context == ".icon-btn"

    def test_empty_button_with_no_attributes_falls_back_to_position(self, agent):
        result = agent.run_checks(
            make_page(buttons=[ButtonData(text="Buy now"), ButtonData(text="", button_type="submit")])
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.EMPTY_BUTTON]
        assert matches[0].context == "submit #2 on the page"

    def test_empty_button_prefers_scraper_computed_selector(self, agent):
        # When the scraper already computed a real selector (its logic is
        # more robust than the id/class/position fallback), that should win.
        result = agent.run_checks(
            make_page(
                buttons=[
                    ButtonData(text="", id="cart", selector="header > nav > button:nth-of-type(2)", section="Header")
                ]
            )
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.EMPTY_BUTTON]
        assert matches[0].context == "header > nav > button:nth-of-type(2)"
        assert matches[0].section == "Header"


class TestElementEvidence:
    def test_missing_alt_text_carries_selector_and_section(self, agent):
        result = agent.run_checks(
            make_page(
                images=[
                    ImageData(
                        src="https://example.com/hero.png",
                        alt=None,
                        selector="#hero img",
                        section="Header",
                        width=1200,
                        height=400,
                    )
                ]
            )
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MISSING_ALT_TEXT]
        assert matches[0].selector == "#hero img"
        assert matches[0].section == "Header"

    def test_recommendation_carries_selector_and_section_through(self, agent):
        page = make_page(
            images=[
                ImageData(src="https://example.com/hero.png", alt=None, selector="#hero img", section="Header")
            ]
        )
        result = agent.run_checks(page)
        finding = next(f for f in result.findings if f.check == AccessibilityCheck.MISSING_ALT_TEXT)
        assert finding.selector == "#hero img"

        from agents.accessibility import _finding_to_recommendation

        rec = _finding_to_recommendation(finding)
        assert rec.selector == "#hero img"
        assert rec.section == "Header"
        assert rec.ai_suggestion is None


class TestMissingLabels:
    def test_unlabeled_field_flagged(self, agent):
        result = agent.run_checks(
            make_page(inputs=[InputData(type="email", id="e", name="email", has_label=False)])
        )
        matches = [f for f in result.findings if f.check == AccessibilityCheck.MISSING_LABEL]
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM
        assert matches[0].context == "email"

    def test_labeled_field_not_flagged(self, agent):
        result = agent.run_checks(
            make_page(inputs=[InputData(type="email", id="e", name="email", has_label=True)])
        )
        checks = [f.check for f in result.findings]
        assert AccessibilityCheck.MISSING_LABEL not in checks


class TestScoringCap:
    def test_many_findings_in_one_check_are_capped(self, agent):
        # 10 missing-alt images * HIGH(10) = 100 points, but the per-check
        # cap of 30 should keep this from zeroing the whole score.
        images = [ImageData(src=f"img{i}.png", alt=None) for i in range(10)]
        result = agent.run_checks(make_page(images=images))
        assert len(result.findings) == 10
        assert result.score == 70.0  # 100 - min(100, 30)

    def test_score_never_goes_below_zero(self, agent):
        page = make_page(
            title=None,
            h1_tags=["A", "B", "C"],
            images=[ImageData(src=f"img{i}.png", alt=None) for i in range(20)],
            buttons=[ButtonData(text="") for _ in range(20)],
            inputs=[InputData(type="text", id=f"f{i}", has_label=False) for i in range(20)],
        )
        result = agent.run_checks(page)
        assert result.score == 0.0


class TestAnalyzeWrapper:
    async def test_analyze_returns_category_result(self, agent):
        page = make_page(title=None)
        category_result = await agent.analyze("https://example.com", {"page_data": page})

        assert category_result.category == AuditCategory.ACCESSIBILITY
        assert category_result.score == 90.0
        assert len(category_result.recommendations) == 1
        assert category_result.raw_data["findings"][0]["check"] == "missing_page_title"

    async def test_analyze_accepts_plain_dict_page_data(self, agent):
        page_dict = make_page().model_dump()
        category_result = await agent.analyze("https://example.com", {"page_data": page_dict})

        assert category_result.score == 100.0
        assert category_result.recommendations == []

    async def test_analyze_raises_on_missing_page_data(self, agent):
        with pytest.raises(ValueError):
            await agent.analyze("https://example.com", {})


# ---------------------------------------------------------------------------
# Evidence, standards mapping, and de-duplication
# ---------------------------------------------------------------------------

class TestWcagMapping:
    async def test_every_finding_cites_a_wcag_criterion(self, agent):
        """A report that grades accessibility has to say what it graded against."""
        page = make_page(
            title=None,
            h1_tags=["A", "B"],
            images=[ImageData(src="logo.png", alt=None)],
            buttons=[ButtonData(text="")],
            inputs=[InputData(type="text", name="email", has_label=False)],
        )
        result = agent.run_checks(page)

        assert len(result.findings) == 5
        for finding in result.findings:
            assert finding.wcag_criterion is not None
            assert finding.wcag_criterion.startswith("WCAG ")

    async def test_criterion_reaches_the_recommendation(self, agent):
        page = make_page(buttons=[ButtonData(text="")])
        category_result = await agent.analyze("https://example.com", {"page_data": page})

        assert category_result.recommendations[0].wcag_criterion == (
            "WCAG 4.1.2 — Name, Role, Value (Level A)"
        )


class TestAccessibleNameResolution:
    def test_uses_the_scrapers_resolved_name(self, agent):
        """aria-labelledby and title give a real name; the old text-only check missed both."""
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="Close dialog", name_source="aria-labelledby"),
            ButtonData(text="", accessible_name="Search", name_source="title"),
        ])

        assert agent.run_checks(page).findings == []

    def test_empty_resolved_name_is_still_flagged(self, agent):
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", name_source="none", selector="#buy"),
        ])
        findings = agent.run_checks(page).findings

        assert len(findings) == 1
        assert findings[0].check == AccessibilityCheck.EMPTY_BUTTON

    def test_falls_back_to_text_when_name_was_not_computed(self, agent):
        """Payloads captured before accessible_name existed must still work."""
        page = make_page(buttons=[ButtonData(text="")])

        assert len(agent.run_checks(page).findings) == 1

    def test_finding_explains_how_the_name_resolved_to_nothing(self, agent):
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", name_source="none", selector="#buy"),
        ])
        finding = agent.run_checks(page).findings[0]

        assert "aria-labelledby" in finding.accessible_name_computation
        assert "accessible name is empty" in finding.accessible_name_computation

    def test_dom_excerpt_is_carried_as_evidence(self, agent):
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", selector="#buy",
                       dom_excerpt='<button id="buy"><svg/></button>'),
        ])
        finding = agent.run_checks(page).findings[0]

        assert finding.dom_excerpt == '<button id="buy"><svg/></button>'


class TestDeduplication:
    def test_distinct_elements_are_all_kept(self, agent):
        """Seven nameless buttons are seven real problems, not one."""
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", selector=f"#b{i}") for i in range(7)
        ])

        assert len(agent.run_checks(page).findings) == 7

    def test_same_element_reported_once(self, agent):
        """A [role=button] wrapping a <button> resolves to one selector, not two findings."""
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", selector="#same"),
            ButtonData(text="", accessible_name="", selector="#same"),
        ])

        assert len(agent.run_checks(page).findings) == 1

    def test_page_level_findings_are_never_merged_away(self, agent):
        page = make_page(title=None, h1_tags=["A", "B"])
        checks = [f.check for f in agent.run_checks(page).findings]

        assert AccessibilityCheck.MISSING_PAGE_TITLE in checks
        assert AccessibilityCheck.MULTIPLE_H1 in checks


class TestCoverageAndProvenance:
    async def test_coverage_lists_what_was_and_was_not_tested(self, agent):
        category_result = await agent.analyze(
            "https://example.com", {"page_data": make_page()}
        )
        coverage = category_result.coverage

        assert coverage is not None
        assert len(coverage.checks_run) == len(AccessibilityCheck)
        assert "Color contrast ratios" in coverage.checks_not_covered
        assert coverage.method is CoverageMethod.AUTOMATED

    async def test_findings_are_marked_as_automated_and_certain(self, agent):
        page = make_page(buttons=[ButtonData(text="", accessible_name="")])
        rec = (await agent.analyze("https://example.com", {"page_data": page})).recommendations[0]

        assert rec.detection is DetectionMethod.AUTOMATED
        assert rec.confidence is ConfidenceLevel.HIGH
        assert rec.rule_id == "empty_button"

    async def test_score_explanation_shows_the_arithmetic(self, agent):
        page = make_page(buttons=[
            ButtonData(text="", accessible_name="", selector=f"#b{i}") for i in range(7)
        ])
        category_result = await agent.analyze("https://example.com", {"page_data": page})

        assert category_result.score == 70.0
        assert "= 70." in category_result.score_explanation

    async def test_summary_states_the_tested_scope(self, agent):
        """"No issues" must not read as "accessibility is fine"."""
        category_result = await agent.analyze(
            "https://example.com", {"page_data": make_page()}
        )

        assert "5 automated checks" in category_result.summary
        assert "issue(s)" not in category_result.summary

    async def test_summary_pluralizes_properly(self, agent):
        page = make_page(buttons=[ButtonData(text="", accessible_name="")])
        summary = (await agent.analyze("https://example.com", {"page_data": page})).summary

        assert "1 accessibility issue " in summary
