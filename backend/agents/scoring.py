"""
Shared scoring utility for rule-based agents.

Turns a list of findings (anything with `.check` and `.severity` attributes)
into a single 0-100 score: start at 100 and deduct points per finding based
on severity, capping how much any single check category can deduct so one
noisy check (e.g. 40 images missing alt text) can't zero out the whole score
by itself.

Every score also comes back with the arithmetic that produced it
(`score_with_explanation`). A number a reader can't reproduce is an assertion,
not a measurement, and "how do seven issues become 70?" has to be answerable
from the report itself rather than from this source file.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from labels import humanize
from models.schemas import Severity

DEFAULT_SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 10,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
    Severity.INFO: 0,
}

DEFAULT_CATEGORY_DEDUCTION_CAP = 30.0

# A category containing an unresolved critical failure cannot present as
# healthy, however few findings it has: the deduction model alone would let a
# single critical issue score 85, which reads as "minor polish needed". The cap
# is applied *after* deductions (it can only lower a score, never raise one)
# and is always stated in the explanation wherever it bites, so it's a
# documented rule rather than another unexplained number.
CRITICAL_FAILURE_SCORE_CAP = 50.0


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
    score, _ = score_with_explanation(findings, severity_weight, category_cap)
    return score


def score_with_explanation(
    findings: Iterable[_Finding],
    severity_weight: dict[Severity, float] = DEFAULT_SEVERITY_WEIGHT,
    category_cap: float = DEFAULT_CATEGORY_DEDUCTION_CAP,
) -> tuple[float, str]:
    """Same scoring as `score_from_findings`, plus a one-line derivation of it."""
    findings = list(findings)
    if not findings:
        return 100.0, "No findings: 100 - 0 = 100."

    deductions_by_check: dict[object, float] = {}
    counts_by_check: dict[object, int] = {}
    has_critical = False
    for finding in findings:
        deductions_by_check.setdefault(finding.check, 0.0)
        deductions_by_check[finding.check] += severity_weight[finding.severity]
        counts_by_check[finding.check] = counts_by_check.get(finding.check, 0) + 1
        if finding.severity is Severity.CRITICAL:
            has_critical = True

    parts: list[str] = []
    total_deduction = 0.0
    for check, raw_deduction in deductions_by_check.items():
        applied = min(raw_deduction, category_cap)
        total_deduction += applied
        label = humanize(check).lower()
        piece = f"{counts_by_check[check]} x {label} = -{raw_deduction:g}"
        if applied < raw_deduction:
            piece += f" (capped at -{category_cap:g})"
        parts.append(piece)

    score = max(0.0, 100.0 - total_deduction)
    explanation = f"100 - [{'; '.join(parts)}] = {score:g}."

    if has_critical and score > CRITICAL_FAILURE_SCORE_CAP:
        explanation += (
            f" Capped at {CRITICAL_FAILURE_SCORE_CAP:g} because at least one critical failure is "
            "unresolved."
        )
        score = CRITICAL_FAILURE_SCORE_CAP

    return score, explanation
