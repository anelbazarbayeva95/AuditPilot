"""
Unit tests for the shared scoring utility used by all rule-based agents.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.scoring import score_from_findings
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
