"""Unit tests for PDF report generation (Milestone 8, +Visual section in Milestone 11). No network/Chrome needed."""

from __future__ import annotations

import base64
import re
import zlib
from datetime import datetime, timezone

from pdf_report import build_pdf_report, build_pdf_report_from_structured
from models.schemas import (
    AuditCategory,
    AuditResult,
    CategoryCoverage,
    CategoryResult,
    ConfidenceLevel,
    CoverageMethod,
    DetectionMethod,
    EffortLevel,
    Evidence,
    ImpactLevel,
    PerformanceRunConfig,
    Recommendation,
    ReportSummary,
    RunContext,
    ScoreStatus,
    ScreenshotQuality,
    Severity,
    StructuredAuditReport,
    TimingBand,
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


# ---------------------------------------------------------------------------
# Rendered-output assertions
#
# The old tests only checked that bytes came back starting with %PDF, which is
# true of a report that duplicates every finding, leaks enum names, and ships
# anonymous metadata. These read the text layer back out and assert on what a
# reader actually sees.
# ---------------------------------------------------------------------------

def pdf_page_texts(pdf_bytes: bytes) -> list[str]:
    """Decompress each content stream and recover its visible text."""
    pages = []
    for match in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", pdf_bytes, re.S):
        body = match.group(2)
        stream = re.search(rb"stream\r?\n", body)
        if not stream:
            continue
        head = body[:stream.start()]
        if b"/Image" in head:
            continue
        raw = body[stream.end():body.rfind(b"endstream")].strip()
        try:
            if b"ASCII85" in head:
                raw = base64.a85decode(raw[:-2] if raw.endswith(b"~>") else raw, adobe=False)
            decoded = zlib.decompress(raw)
        except Exception:  # noqa: BLE001 - not a text stream
            continue
        if b"BT" not in decoded:
            continue
        chunks = re.findall(rb"\((?:\\.|[^()\\])*\)", decoded)
        pages.append(b" ".join(c[1:-1] for c in chunks).decode("latin-1"))
    return pages


def pdf_text(pdf_bytes: bytes) -> str:
    return " ".join(pdf_page_texts(pdf_bytes))


def make_structured_report(**overrides) -> StructuredAuditReport:
    def a11y_rec(index: int) -> Recommendation:
        return Recommendation(
            title="Button with no accessible name",
            description="The button has no accessible name.",
            severity=Severity.HIGH, category=AuditCategory.ACCESSIBILITY,
            selector=f"section > div:nth-of-type({index}) > button", section="Main content",
            rule_id="empty_button", detection=DetectionMethod.AUTOMATED,
            confidence=ConfidenceLevel.HIGH, impact=ImpactLevel.HIGH, effort=EffortLevel.QUICK,
            timing=TimingBand.IMMEDIATE, wcag_criterion="WCAG 4.1.2 — Name, Role, Value (Level A)",
            validation="Re-run this audit and confirm the finding is gone.",
            evidence=Evidence(dom_excerpt=f'<button class="b{index}"><svg/></button>'),
        )

    defaults = dict(
        summary=ReportSummary(
            overall_score=61.3,
            category_scores={"accessibility": 70.0, "seo": 100.0, "performance": 25.0,
                             "copy": 75.0, "visual": None},
            issue_counts={"high": 7},
            weights={"accessibility": 0.29, "seo": 0.24, "performance": 0.29, "copy": 0.18},
            excluded_categories={"visual": "insufficient evidence"},
            score_explanation="Weighted average: Accessibility 70 x 29% ... = 61.",
        ),
        accessibility=CategoryResult(
            category=AuditCategory.ACCESSIBILITY, score=70.0,
            score_explanation="100 - [7 x button with no accessible name = -70 (capped at -30)] = 70.",
            coverage=CategoryCoverage(
                checks_run=["Missing alt text", "Button with no accessible name"],
                checks_not_covered=["Color contrast ratios"], method=CoverageMethod.AUTOMATED,
            ),
            summary="7 accessibility issues found across the 5 automated checks performed.",
            recommendations=[a11y_rec(i) for i in range(1, 8)],
        ),
        seo=CategoryResult(category=AuditCategory.SEO, score=100.0,
                           summary="No issues found across the 6 on-page checks performed."),
        performance=CategoryResult(
            category=AuditCategory.PERFORMANCE, score=25.0,
            recommendations=[Recommendation(
                title="Slow LCP (Largest Contentful Paint)",
                description="Optimize the largest above-the-fold element.",
                severity=Severity.HIGH, category=AuditCategory.PERFORMANCE, rule_id="slow_lcp",
                detection=DetectionMethod.AUTOMATED, impact=ImpactLevel.HIGH,
                effort=EffortLevel.INVOLVED, timing=TimingBand.NEXT_SPRINT,
                evidence=Evidence(measured_value="6480 ms", threshold="good is <= 2500 ms"),
            )],
            raw_data={"metrics": {"lcp_ms": 6480.0, "cls": 0.31, "inp_ms": 420.0},
                      "opportunities": [{"audit_id": "render-blocking-resources",
                                         "title": "Eliminate render-blocking resources",
                                         "savings_ms": 1240.0, "savings_bytes": 98304,
                                         "resources": ["https://example.com/main.css"]}]},
        ),
        copy=CategoryResult(
            category=AuditCategory.COPY, score=75.0,
            coverage=CategoryCoverage(checks_run=["CTA quality"], checks_not_covered=[],
                                      method=CoverageMethod.AI_ASSISTED),
            recommendations=[Recommendation(
                title="CTA quality", description="Use a specific CTA label.",
                severity=Severity.MEDIUM, category=AuditCategory.COPY, rule_id="cta_quality",
                detection=DetectionMethod.AI_GENERATED, confidence=ConfidenceLevel.MEDIUM,
                impact=ImpactLevel.MEDIUM, effort=EffortLevel.QUICK, timing=TimingBand.NEXT_SPRINT,
            )],
            raw_data={"strengths": [{"dimension": "readability", "point": "Concise.",
                                     "confidence": "medium"}],
                      "weaknesses": [{"dimension": "cta_quality", "point": "Generic label.",
                                      "confidence": "high"}]},
        ),
        visual=CategoryResult(
            category=AuditCategory.VISUAL, score=None,
            score_status=ScoreStatus.INSUFFICIENT_EVIDENCE,
            summary="Visual analysis was not performed. The page did not finish rendering.",
        ),
        run_context=RunContext(
            started_at=datetime(2026, 8, 17, 4, 9, tzinfo=timezone.utc),
            finished_at=datetime(2026, 8, 17, 4, 11, tzinfo=timezone.utc),
            requested_url="https://example.com", final_url="https://example.com",
            http_status=200, viewport="1280x900", user_agent="Mozilla/5.0",
            scraper_wait_until="domcontentloaded",
            performance_run=PerformanceRunConfig(
                lighthouse_version="12.2.1", form_factor="desktop",
                throttling="simulated, 10240 kbps down", runs=1,
            ),
            scope_limitations=["A single URL was audited."],
        ),
    )
    defaults.update(overrides)
    report = StructuredAuditReport(**defaults)
    report.recommendations = [
        r for cat in (report.accessibility, report.seo, report.performance, report.copy,
                      report.visual)
        for r in cat.recommendations
    ]
    return report


class TestDocumentMetadata:
    def test_metadata_is_populated_not_anonymous(self):
        """An untitled, authorless PDF is unusable for document management."""
        pdf = build_pdf_report_from_structured("https://example.com", make_structured_report())

        assert b"/Title" in pdf and b"anonymous" not in pdf
        assert b"AuditPilot" in pdf
        assert re.search(rb"/Subject\s*\(", pdf)
        assert re.search(rb"/Keywords\s*\(", pdf)

    def test_document_language_is_declared(self):
        """Assistive technology needs /Lang to read the report correctly."""
        pdf = build_pdf_report_from_structured("https://example.com", make_structured_report())

        assert re.findall(rb"/Lang\s*\(([^)]*)\)", pdf) == [b"en-US"]

    def test_document_has_navigable_bookmarks(self):
        pdf = build_pdf_report_from_structured("https://example.com", make_structured_report())

        assert b"/Outlines" in pdf

    def test_pages_are_numbered(self):
        pdf = build_pdf_report_from_structured("https://example.com", make_structured_report())

        assert "Page 2 of" in pdf_text(pdf)


class TestEditorialQuality:
    def test_no_machine_identifiers_in_the_body(self):
        """Raw enum values belong in the appendix, never in prose."""
        pages = pdf_page_texts(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )
        body = " ".join(pages[:-1])  # everything before the appendix

        for machine_name in ("cta_quality", "slow_lcp", "empty_button", "visual_hierarchy"):
            assert machine_name not in body

    def test_appendix_does_carry_the_machine_identifiers(self):
        pages = pdf_page_texts(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "empty_button" in pages[-1]

    def test_no_unedited_pluralization(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "issue(s)" not in text
        assert "(s)" not in text

    def test_markup_in_findings_is_escaped_not_swallowed(self):
        """Findings quote real markup; unescaped angle brackets would vanish."""
        report = make_structured_report()
        report.seo.recommendations = [Recommendation(
            title="Missing page title", description="Page is missing a <title> element.",
            severity=Severity.HIGH, category=AuditCategory.SEO, rule_id="missing_title",
        )]
        text = pdf_text(build_pdf_report_from_structured("https://example.com", report))
        # ReportLab emits the escaped characters as their own glyph runs, so the
        # recovered text layer has extra spacing the rendered page doesn't.
        normalized = text.replace("< ", "<").replace(" >", ">")

        assert "<title>" in normalized
        assert "&lt;" not in text  # escaped for the parser, not shown to the reader


class TestNoDuplication:
    def test_findings_are_not_printed_twice(self):
        """The old trailing 'Recommendations' section repeated every finding verbatim."""
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert text.count("The button has no accessible name.") == 1

    def test_repeated_occurrences_are_grouped_with_a_count(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "7 occurrences" in text


class TestEvidenceAndMethodology:
    def test_performance_metrics_are_printed(self):
        """The reviewed report showed 25/100 with no LCP value anywhere."""
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Largest Contentful Paint" in text
        assert "6,480 ms" in text

    def test_performance_opportunities_name_real_resources(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Eliminate render-blocking resources" in text
        assert "main.css" in text

    def test_methodology_records_the_run_conditions(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Methodology" in text
        assert "12.2.1" in text          # Lighthouse version
        assert "desktop" in text          # form factor
        assert "1280x900" in text         # viewport

    def test_coverage_states_what_was_not_tested(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Not tested" in text
        assert "Color contrast ratios" in text

    def test_wcag_criteria_are_cited(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "WCAG 4.1.2" in text

    def test_scores_carry_their_derivation(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Score derivation" in text
        assert "capped at -30" in text


class TestDegradedScreenshotDisclosure:
    def test_incomplete_render_is_labelled_as_a_failed_capture(self):
        report = make_structured_report(
            screenshot_quality=ScreenshotQuality(
                status="degraded", dominant_color_pct=71.3,
                reason="The page did not finish rendering before capture.",
            ),
        )
        report.screenshot_viewport_base64 = base64.b64encode(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )).decode("ascii")

        text = pdf_text(build_pdf_report_from_structured("https://example.com", report))

        assert "Incomplete render" in text
        assert "not used for assessment" in text
        assert "Visual analysis was skipped" in text

    def test_insufficient_evidence_shows_in_the_scorecard(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Insufficient evidence" in text


class TestActionPlan:
    def test_action_plan_is_ranked_and_deduplicated(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Priority action plan" in text
        # Seven identical button findings collapse into one ranked action.
        assert text.count("Button with no accessible name") <= 3

    def test_owner_is_never_invented(self):
        text = pdf_text(
            build_pdf_report_from_structured("https://example.com", make_structured_report())
        )

        assert "Unassigned" in text
        assert "does not infer who maintains a component" in text
