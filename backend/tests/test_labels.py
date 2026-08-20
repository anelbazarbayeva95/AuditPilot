"""Unit tests for the editorial helpers in labels.py."""

from __future__ import annotations

import pytest

from labels import humanize, normalize_page_text, pluralize
from models.schemas import AccessibilityCheck, CopyDimension, PerformanceCheck


class TestHumanize:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # The exact strings a naive .title() got wrong in the shipped report.
            ("cta_quality", "CTA quality"),
            ("slow_lcp", "Slow LCP (Largest Contentful Paint)"),
            ("high_cls", "High CLS (Cumulative Layout Shift)"),
            ("slow_inp", "Slow INP (Interaction to Next Paint)"),
            ("seo", "SEO"),
        ],
    )
    def test_acronyms_are_not_title_cased(self, raw, expected):
        assert humanize(raw) == expected

    def test_accepts_enums_directly(self):
        assert humanize(CopyDimension.VALUE_PROPOSITION_CLARITY) == "Value proposition clarity"
        assert humanize(AccessibilityCheck.EMPTY_BUTTON) == "Button with no accessible name"
        assert humanize(PerformanceCheck.SLOW_LCP).startswith("Slow LCP")

    def test_unknown_identifier_falls_back_to_sentence_case(self):
        assert humanize("some_new_check") == "Some new check"

    def test_none_is_empty_string(self):
        assert humanize(None) == ""

    def test_every_check_and_dimension_has_a_real_label(self):
        """No enum the agents can emit may reach a reader as a machine name."""
        for enum in (AccessibilityCheck, CopyDimension, PerformanceCheck):
            for member in enum:
                label = humanize(member)
                assert "_" not in label, f"{member} rendered as {label!r}"
                assert label[0].isupper()


class TestPluralize:
    def test_singular(self):
        assert pluralize(1, "issue") == "1 issue"

    def test_plural(self):
        assert pluralize(7, "issue") == "7 issues"

    def test_zero_is_plural(self):
        assert pluralize(0, "issue") == "0 issues"

    def test_irregular_plural(self):
        assert pluralize(4, "weakness", "weaknesses") == "4 weaknesses"


class TestNormalizePageText:
    def test_collapses_line_breaks_that_would_concatenate_headings(self):
        """The exact failure that produced 'KYLIAN MBAPPEMERCURIAL SUPERFLY'."""
        assert normalize_page_text("KYLIAN MBAPPÉ\nMERCURIAL SUPERFLY") == (
            "KYLIAN MBAPPÉ MERCURIAL SUPERFLY"
        )

    def test_collapses_runs_of_whitespace(self):
        assert normalize_page_text("  Shop    the   JA 4  ") == "Shop the JA 4"

    def test_whitespace_only_becomes_none(self):
        assert normalize_page_text("   \n  ") is None

    def test_none_passes_through(self):
        assert normalize_page_text(None) is None
