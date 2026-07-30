"""
Unit tests for the CopyAgent prompt template (agents/prompts/copy.py).
"""

from __future__ import annotations

from agents.prompts.copy import build_copy_prompt
from models.schemas import ButtonData, LinkData, ScrapedPageData


def make_page(**overrides) -> ScrapedPageData:
    defaults = dict(
        url="https://example.com",
        title="Acme Widgets — Ship Faster",
        meta_description="Acme helps teams ship widgets 10x faster.",
        h1_tags=["Ship widgets faster"],
        h2_tags=["Why Acme", "Pricing"],
        images=[],
        buttons=[ButtonData(text="Start your free trial")],
        links=[LinkData(text="See customer stories", href="/customers")],
        inputs=[],
    )
    defaults.update(overrides)
    return ScrapedPageData(**defaults)


def test_prompt_includes_all_five_dimensions():
    prompt = build_copy_prompt(make_page())
    for dimension in [
        "value_proposition_clarity",
        "readability",
        "cta_quality",
        "jargon",
        "trust_signals",
    ]:
        assert dimension in prompt


def test_prompt_includes_page_content():
    page = make_page()
    prompt = build_copy_prompt(page)
    assert page.title in prompt
    assert page.meta_description in prompt
    assert "Ship widgets faster" in prompt
    assert "Start your free trial" in prompt
    assert "See customer stories" in prompt


def test_prompt_requests_json_schema():
    prompt = build_copy_prompt(make_page())
    assert '"strengths"' in prompt
    assert '"weaknesses"' in prompt
    assert '"recommendations"' in prompt
    assert '"score"' in prompt


def test_prompt_uses_placeholders_for_missing_data():
    page = make_page(title=None, meta_description=None, h1_tags=[], buttons=[], links=[])
    prompt = build_copy_prompt(page)
    assert "(missing)" in prompt
    assert "(none)" in prompt
