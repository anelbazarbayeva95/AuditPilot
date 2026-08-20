"""
Unit tests for the shared scoring utility used by all rule-based agents.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.scoring import (
    CRITICAL_FAILURE_SCORE_CAP,
    score_from_findings,
    score_with_explanation,
)
from models.schemas import Severity


@dataclass
class _FakeFinding:
    check: str
    severity: Severity


def test_no_findings_scores_100():
    assert score_from_findings([]) == 100.0


def test_single_high_severity_deduction():
    findings = [_FakeFinding(check="a", severity=Severity.HIGH)]
    assert score_from_findings(findings) == 90.0


def test_deductions_within_a_check_accumulate_up_to_cap():
    # 5 MEDIUM findings in the same check = 25, under the default 30 cap.
    findings = [_FakeFinding(check="a", severity=Severity.MEDIUM) for _ in range(5)]
    assert score_from_findings(findings) == 75.0


def test_deductions_within_a_check_are_capped():
    # 10 HIGH findings in the same check would be 100 points, but capped at 30.
    findings = [_FakeFinding(check="a", severity=Severity.HIGH) for _ in range(10)]
    assert score_from_findings(findings) == 70.0


def test_cap_applies_per_check_not_globally():
    # Two different checks, each individually capped at 30 -> 60 total deduction.
    findings = [_FakeFinding(check="a", severity=Severity.HIGH) for _ in range(10)] + [
        _FakeFinding(check="b", severity=Severity.HIGH) for _ in range(10)
    ]
    assert score_from_findings(findings) == 40.0


def test_score_floors_at_zero():
    findings = [_FakeFinding(check=f"check-{i}", severity=Severity.CRITICAL) for i in range(10)]
    # 10 distinct checks * 15 (CRITICAL, well under their own cap) = 150 total.
    assert score_from_findings(findings) == 0.0


def test_custom_severity_weight_and_cap():
    findings = [_FakeFinding(check="a", severity=Severity.LOW) for _ in range(3)]
    score = score_from_findings(
        findings, severity_weight={Severity.LOW: 40.0}, category_cap=50.0
    )
    assert score == 50.0  # 3 * 40 = 120, capped at 50


# ---------------------------------------------------------------------------
# Explainability and the critical-failure cap
# ---------------------------------------------------------------------------

def test_explanation_reproduces_the_arithmetic():
    """A reader must be able to check the number, not just accept it."""
    findings = [_FakeFinding(check="empty_button", severity=Severity.HIGH) for _ in range(7)]

    score, explanation = score_with_explanation(findings)

    assert score == 70.0
    assert "7 x" in explanation
    assert "-70" in explanation          # the raw deduction
    assert "capped at -30" in explanation  # and why it wasn't applied in full
    assert explanation.endswith("= 70.")


def test_explanation_uses_human_labels_not_enum_values():
    findings = [_FakeFinding(check="empty_button", severity=Severity.HIGH)]

    _, explanation = score_with_explanation(findings)

    assert "empty_button" not in explanation
    assert "button with no accessible name" in explanation


def test_explanation_when_nothing_was_found():
    score, explanation = score_with_explanation([])

    assert score == 100.0
    assert explanation == "No findings: 100 - 0 = 100."


def test_critical_failure_caps_the_score():
    """One critical issue must not leave a category reading as healthy."""
    findings = [_FakeFinding(check="a", severity=Severity.CRITICAL)]

    score, explanation = score_with_explanation(findings)

    assert score == CRITICAL_FAILURE_SCORE_CAP == 50.0
    assert "critical failure" in explanation


def test_critical_cap_never_raises_a_worse_score():
    findings = [_FakeFinding(check="a", severity=Severity.CRITICAL)] + [
        _FakeFinding(check=f"c{i}", severity=Severity.HIGH) for i in range(6)
    ]

    score, _ = score_with_explanation(findings)

    assert score == 25.0  # 100 - 15 (critical) - 60 (6 checks x 10) = 25, already below the cap


def test_score_from_findings_matches_the_explained_score():
    findings = [_FakeFinding(check="a", severity=Severity.MEDIUM) for _ in range(3)]

    assert score_from_findings(findings) == score_with_explanation(findings)[0]
