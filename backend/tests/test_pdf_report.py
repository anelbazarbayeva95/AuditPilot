"""Unit tests for PDF report generation (Milestone 8, +Visual section in Milestone 11). No network/Chrome needed."""

from __future__ import annotations

import base64

from pdf_report import build_pdf_report
from models.schemas import (
    AuditCategory,
    AuditResult,
    CategoryResult,
    Recommendation,
    Severity,
)


def make_result() -> AuditResult:
    return AuditResult(
        overall_score=82.0,
        accessibility=CategoryResult(
            category=AuditCategory.ACCESSIBILITY, score=90.0, summary="Looks good.",
            recommendations=[Recommendation(
                title="Missing Alt Text", description="Image 'logo.png' has no alt.",
                severity=Severity.HIGH, category=AuditCategory.ACCESSIBILITY,
            )],
        ),
        seo=CategoryResult(category=AuditCategory.SEO, score=75.0, summary="A few gaps.", recommendations=[]),
        copy=CategoryResult(
            category=AuditCategory.COPY, score=80.0, summary="Solid copy.",
            recommendations=[Recommendation(
                title="Cta Quality", description="Use a stronger CTA.",
                severity=Severity.MEDIUM, category=AuditCategory.COPY,
            )],
            raw_data={
                "strengths": [{"dimension": "readability", "point": "Clear headline."}],
                "weaknesses": [{"dimension": "cta_quality", "point": "Generic button text."}],
                "recommendations": [{"dimension": "cta_quality", "point": "Use a stronger CTA."}],
                "score": 80.0,
            },
        ),
    )


def test_generates_nonempty_pdf_bytes():
    pdf_bytes = build_pdf_report("https://example.com", make_result())
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_handles_missing_performance_gracefully():
    pdf_bytes = build_pdf_report("https://example.com", make_result(), performance=None)
    assert pdf_bytes.startswith(b"%PDF")


def test_includes_performance_when_provided():
    performance = CategoryResult(
        category=AuditCategory.PERFORMANCE, score=60.0, summary="Some slow metrics.",
        recommendations=[Recommendation(
            title="Slow Lcp", description="LCP is 4200ms.",
            severity=Severity.HIGH, category=AuditCategory.PERFORMANCE,
        )],
    )
    pdf_bytes = build_pdf_report("https://example.com", make_result(), performance=performance)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_includes_visual_section_with_screenshot():
    visual = CategoryResult(
        category=AuditCategory.VISUAL, score=65.0, summary="A few visual issues.",
        recommendations=[Recommendation(
            title="Cta Visibility", description="Move the primary CTA above the fold.",
            severity=Severity.MEDIUM, category=AuditCategory.VISUAL,
        )],
        raw_data={
            "strengths": [{"dimension": "visual_hierarchy", "point": "Clear hero section."}],
            "weaknesses": [{"dimension": "cta_visibility", "point": "CTA is below the fold."}],
            "recommendations": [{"dimension": "cta_visibility", "point": "Move the primary CTA above the fold."}],
            "score": 65.0,
        },
    )
    # A tiny valid 1x1 PNG, base64-encoded, so Image() can actually decode it.
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    screenshot_b64 = base64.b64encode(tiny_png).decode("ascii")

    pdf_bytes = build_pdf_report(
        "https://example.com", make_result(), visual=visual, screenshot_viewport_base64=screenshot_b64
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_handles_missing_visual_gracefully():
    pdf_bytes = build_pdf_report("https://example.com", make_result(), visual=None)
    assert pdf_bytes.startswith(b"%PDF")


def test_ignores_undecodable_screenshot_bytes():
    pdf_bytes = build_pdf_report(
        "https://example.com", make_result(), screenshot_viewport_base64="not-valid-base64!!!"
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_handles_all_empty_recommendations():
    result = AuditResult(
        overall_score=100.0,
        accessibility=CategoryResult(category=AuditCategory.ACCESSIBILITY, score=100.0, recommendations=[]),
        seo=CategoryResult(category=AuditCategory.SEO, score=100.0, recommendations=[]),
        copy=CategoryResult(category=AuditCategory.COPY, score=100.0, recommendations=[], raw_data=None),
    )
    pdf_bytes = build_pdf_report("https://example.com", result)
    assert pdf_bytes.startswith(b"%PDF")
