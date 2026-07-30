"""
Unit tests for the VisualAgent prompt template (agents/prompts/visual.py).
"""

from __future__ import annotations

from agents.prompts.visual import build_visual_prompt


def test_prompt_includes_all_four_dimensions():
    prompt = build_visual_prompt("https://example.com")
    for dimension in [
        "visual_hierarchy",
        "cta_visibility",
        "layout_issues",
        "contrast_problems",
    ]:
        assert dimension in prompt


def test_prompt_includes_url():
    prompt = build_visual_prompt("https://unique-marker.example.com")
    assert "unique-marker.example.com" in prompt


def test_prompt_requests_json_schema():
    prompt = build_visual_prompt("https://example.com")
    assert '"strengths"' in prompt
    assert '"weaknesses"' in prompt
    assert '"recommendations"' in prompt
    assert '"score"' in prompt
