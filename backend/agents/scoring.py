"""
Shared scoring utility for rule-based agents.

Turns a list of findings (anything with `.check` and `.severity` attributes)
into a single 0-100 score: start at 100 and deduct points per finding based
on severity, capping how much any single check category can deduct so one
noisy check (e.g. 40 images missing alt text) can't zero out the whole score
by itself.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from models.schemas import Severity

DEFAULT_SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 10,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
    Severity.INFO: 0,
}

DEFAULT_CATEGORY_DEDUCTION_CAP = 30.0


class _Finding(Protocol):
    check: object
    severity: Severity


def score_from_findings(
    findings: Iterable[_Finding],
    severity_weight: dict[Severity, float] = DEFAULT_SEVERITY_WEIGHT,
    category_cap: float = DEFAULT_CATEGORY_DEDUCTION_CAP,
) -> float:
    """Compute a 0-100 score from a list of findings.

    Findings are grouped by their `.check` identifier; each group's total
    deduction is capped at `category_cap` before being subtracted from 100.
    """
    deductions_by_check: dict[object, float] = {}
    for finding in findings:
        deductions_by_check.setdefault(finding.check, 0.0)
        deductions_by_check[finding.check] += severity_weight[finding.severity]

    total_deduction = sum(min(d, category_cap) for d in deductions_by_check.values())
    return max(0.0, 100.0 - total_deduction)
