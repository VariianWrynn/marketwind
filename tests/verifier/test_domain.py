"""Smoke / construction tests for verifier value objects."""

from __future__ import annotations

from marketwind.verifier.domain import Violation, VerifyResult


def test_violation_roundtrip():
    v = Violation(check="RF-4", locus="sentence[0]", detail="anonymous filler")
    assert (v.check, v.locus, v.detail) == ("RF-4", "sentence[0]", "anonymous filler")


def test_verify_result_fields():
    v = Violation(check="RF-4", locus="sentence[0]", detail="anonymous filler")
    result = VerifyResult(passed=False, violations=[v])
    assert result.passed is False
    assert result.violations == [v]
