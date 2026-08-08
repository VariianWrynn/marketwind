"""G2.3: Claim state machine — minimal lifecycle tracking.

States: drafted → verified | failed → rewritten (retry ≤ 1).
Failure-rate thresholds (D-4): 10% warning, 25% hard halt.
Denominator (D-8): claim-level — (failed + dropped) / all drafted.
Max retry (D-9): 1.
"""

from __future__ import annotations

from dataclasses import dataclass

WARN_THRESHOLD = 0.10
HALT_THRESHOLD = 0.25
MAX_RETRY = 1


@dataclass(frozen=True)
class FailureDigest:
    total_drafts: int
    failed: int
    dropped: int
    failure_rate: float
    warn: bool
    halt: bool
    summary: str


def compute_failure_digest(total_drafts: int, failed: int, dropped: int) -> FailureDigest:
    """Compute failure-rate digest for a report's claims (D-4/D-8).

    Returns a digest with warn/halt flags and an 800-char summary.
    """
    denominator = total_drafts
    if denominator == 0:
        rate = 0.0
    else:
        rate = (failed + dropped) / denominator
    warn = rate >= WARN_THRESHOLD
    halt = rate >= HALT_THRESHOLD
    parts = [
        f"claims: {denominator} drafted, {failed} failed, {dropped} dropped",
        f"failure_rate: {rate:.1%}",
    ]
    if warn:
        parts.append(f"WARN: failure rate {rate:.1%} >= {WARN_THRESHOLD:.0%}")
    if halt:
        parts.append(f"HALT: failure rate {rate:.1%} >= {HALT_THRESHOLD:.0%}")
    summary = " | ".join(parts)
    return FailureDigest(
        total_drafts=denominator, failed=failed, dropped=dropped,
        failure_rate=rate, warn=warn, halt=halt,
        summary=summary[:800],
    )


def can_retry(retry_count: int) -> bool:
    """Whether a claim can be retried (D-9: max 1)."""
    return retry_count < MAX_RETRY
