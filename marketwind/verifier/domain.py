"""Pure value objects for the Verifier. No I/O, no logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    check: str
    locus: str
    detail: str


@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    violations: list[Violation]
