"""
Unit tests for SEOAgent (Milestone 3).

Covers each rule in isolation (title exists, meta description exists,
single h1, Open Graph tags, image alt text), a clean page with no findings,
the per-check deduction cap, and the async `analyze()` orchestrator
entrypoint.
"""

from __future__ import annotations

import pytest

from agents.seo import SEOAgent
from models.schemas import AuditCategory, ImageData, ScrapedPageData, SEOCheck, Severity

_CLEAN_OG = {
    "og:title": "Example Domain",
    "og:description": "An example page.",
    "og:image": "https://example.com/og.png",
}


def make_page(**overrides) -> ScrapedPageData:
    """A clean, fully SEO-compliant page; override individual fields per test."""
    defaults = dict(
        url="https://example.com",
        title="Example Domain",
        meta_description="An example page.",
        h1_tags=["Welcome"],
        h2_tags=[],
        images=[ImageData(src="logo.png", alt="Company logo")],
        buttons=[],
        links=[],
        inputs=[],
        open_graph=dict(_CLEAN_OG),
    )
    defaults.update(overrides)
    return ScrapedPageData(**defaults)


@pytest.fixture
def agent() -> SEOAgent:
    return SEOAgent()


class TestCleanPage:
    def test_clean_page_has_no_findings(self, agent):
        result = agent.run_checks(make_page())
        assert result.findings == []

    def test_clean_page_scores_100(self, agent):
        result = agent.run_checks(make_page())
        assert result.score == 100.0


class TestTitleExists:
    @pytest.mark.parametrize("title", [None, "", "   "])
    def test_flags_missing_or_empty_title(self, agent, title):
        result = agent.run_checks(make_page(title=title))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_TITLE in checks

    def test_present_title_not_flagged(self, agent):
        result = agent.run_checks(make_page(title="Real Title"))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_TITLE not in checks

    def test_deducts_expected_points(self, agent):
        result = agent.run_checks(make_page(title=None))
        assert result.score == 90.0  # 100 - HIGH(10)


class TestMetaDescriptionExists:
    @pytest.mark.parametrize("meta_description", [None, "", "   "])
    def test_flags_missing_or_empty_meta_description(self, agent, meta_description):
        result = agent.run_checks(make_page(meta_description=meta_description))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_META_DESCRIPTION in checks

    def test_present_meta_description_not_flagged(self, agent):
        result = agent.run_checks(make_page(meta_description="Something descriptive."))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_META_DESCRIPTION not in checks

    def test_deducts_expected_points(self, agent):
        result = agent.run_checks(make_page(meta_description=None))
        assert result.score == 90.0  # 100 - HIGH(10)


class TestSingleH1:
    def test_single_h1_not_flagged(self, agent):
        result = agent.run_checks(make_page(h1_tags=["Only One"]))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_H1 not in checks
        assert SEOCheck.MULTIPLE_H1 not in checks

    def test_zero_h1_flagged_as_missing(self, agent):
        result = agent.run_checks(make_page(h1_tags=[]))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_H1 in checks
        assert SEOCheck.MULTIPLE_H1 not in checks

    def test_multiple_h1_flagged(self, agent):
        result = agent.run_checks(make_page(h1_tags=["First", "Second"]))
        matches = [f for f in result.findings if f.check == SEOCheck.MULTIPLE_H1]
        assert len(matches) == 1
        assert matches[0].severity == Severity.MEDIUM

    def test_multiple_h1_message_names_the_actual_headings(self, agent):
        result = agent.run_checks(make_page(h1_tags=["Shop Now", "Welcome Back"]))
        matches = [f for f in result.findings if f.check == SEOCheck.MULTIPLE_H1]
        assert "Shop Now" in matches[0].message
        assert "Welcome Back" in matches[0].message

    def test_deducts_expected_points(self, agent):
        result = agent.run_checks(make_page(h1_tags=[]))
        assert result.score == 95.0  # 100 - MEDIUM(5)


class TestOpenGraphTags:
    def test_all_required_tags_present_not_flagged(self, agent):
        result = agent.run_checks(make_page())
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_OPEN_GRAPH_TAGS not in checks

    def test_missing_single_tag_flagged(self, agent):
        og = dict(_CLEAN_OG)
        del og["og:image"]
        result = agent.run_checks(make_page(open_graph=og))
        matches = [f for f in result.findings if f.check == SEOCheck.MISSING_OPEN_GRAPH_TAGS]
        assert len(matches) == 1
        assert matches[0].context == "og:image"

    def test_missing_all_tags_flags_each(self, agent):
        result = agent.run_checks(make_page(open_graph={}))
        matches = [f for f in result.findings if f.check == SEOCheck.MISSING_OPEN_GRAPH_TAGS]
        assert len(matches) == 3
        assert {f.context for f in matches} == {"og:title", "og:description", "og:image"}

    def test_empty_tag_value_flagged(self, agent):
        og = dict(_CLEAN_OG)
        og["og:description"] = "   "
        result = agent.run_checks(make_page(open_graph=og))
        matches = [f for f in result.findings if f.check == SEOCheck.MISSING_OPEN_GRAPH_TAGS]
        assert any(f.context == "og:description" for f in matches)


class TestImageAltText:
    def test_missing_alt_attribute_flagged(self, agent):
        result = agent.run_checks(make_page(images=[ImageData(src="hero.png", alt=None)]))
        matches = [f for f in result.findings if f.check == SEOCheck.MISSING_IMAGE_ALT_TEXT]
        assert len(matches) == 1
        assert matches[0].context == "hero.png"
        assert matches[0].severity == Severity.LOW

    def test_empty_alt_is_decorative_and_not_flagged(self, agent):
        result = agent.run_checks(make_page(images=[ImageData(src="divider.png", alt="")]))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_IMAGE_ALT_TEXT not in checks

    def test_present_alt_not_flagged(self, agent):
        result = agent.run_checks(make_page(images=[ImageData(src="hero.png", alt="Hero banner")]))
        checks = [f.check for f in result.findings]
        assert SEOCheck.MISSING_IMAGE_ALT_TEXT not in checks

    def test_missing_alt_carries_selector_and_section(self, agent):
        result = agent.run_checks(
            make_page(
                images=[
                    ImageData(src="hero.png", alt=None, selector="#hero img", section="Header")
                ]
            )
        )
        matches = [f for f in result.findings if f.check == SEOCheck.MISSING_IMAGE_ALT_TEXT]
        assert matches[0].selector == "#hero img"
        assert matches[0].section == "Header"


class TestScoringCap:
    def test_many_missing_alt_images_are_capped(self, agent):
        # 20 missing-alt images * LOW(2) = 40 points, but the per-check cap
        # of 30 should keep this from over-penalizing a single check.
        images = [ImageData(src=f"img{i}.png", alt=None) for i in range(20)]
        result = agent.run_checks(make_page(images=images))
        assert len(result.findings) == 20
        assert result.score == 70.0  # 100 - min(40, 30)

    def test_worst_case_across_all_five_checks_stays_above_zero(self, agent):
        # SEOAgent only has 5 check categories, and 3 of them can only ever
        # produce a single finding each (title, meta description, h1). Even
        # in the worst case the total deduction tops out below 100 — the
        # score floor itself is covered generically in test_scoring.py.
        page = make_page(
            title=None,
            meta_description=None,
            h1_tags=[],
            open_graph={},
            images=[ImageData(src=f"img{i}.png", alt=None) for i in range(20)],
        )
        result = agent.run_checks(page)
        # 10 (title) + 10 (meta) + 5 (h1) + 15 (3 og tags) + 30 (alt, capped) = 70
        assert result.score == 30.0


class TestAnalyzeWrapper:
    async def test_analyze_returns_category_result(self, agent):
        page = make_page(title=None)
        category_result = await agent.analyze("https://example.com", {"page_data": page})

        assert category_result.category == AuditCategory.SEO
        assert category_result.score == 90.0
        assert len(category_result.recommendations) == 1
        assert category_result.raw_data["findings"][0]["check"] == "missing_title"

    async def test_analyze_accepts_plain_dict_page_data(self, agent):
        page_dict = make_page().model_dump()
        category_result = await agent.analyze("https://example.com", {"page_data": page_dict})

        assert category_result.score == 100.0
        assert category_result.recommendations == []

    async def test_analyze_raises_on_missing_page_data(self, agent):
        with pytest.raises(ValueError):
            await agent.analyze("https://example.com", {})
