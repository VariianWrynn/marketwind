"""Tests for G2.3 claim state machine."""

from marketwind.verifier.claim_state import (
    HALT_THRESHOLD,
    MAX_RETRY,
    WARN_THRESHOLD,
    can_retry,
    compute_failure_digest,
)


def test_digest_zero_claims_no_flags():
    d = compute_failure_digest(0, 0, 0)
    assert d.failure_rate == 0.0
    assert d.warn is False
    assert d.halt is False
    assert d.total_drafts == 0


def test_digest_below_threshold_clean():
    d = compute_failure_digest(100, 5, 2)
    assert d.failure_rate == 0.07
    assert d.warn is False
    assert d.halt is False


def test_digest_at_warn_threshold():
    d = compute_failure_digest(100, 10, 0)
    assert d.failure_rate == 0.10
    assert d.warn is True
    assert d.halt is False


def test_digest_at_halt_threshold():
    d = compute_failure_digest(100, 25, 0)
    assert d.failure_rate == 0.25
    assert d.warn is True
    assert d.halt is True


def test_digest_dropped_counts_toward_failure():
    d = compute_failure_digest(10, 1, 2)
    assert d.failure_rate == 0.30
    assert d.halt is True


def test_digest_summary_truncated_at_800():
    d = compute_failure_digest(10, 5, 3)
    assert len(d.summary) <= 800


def test_can_retry_zero():
    assert can_retry(0) is True


def test_can_retry_at_max():
    assert can_retry(MAX_RETRY) is False


def test_max_retry_is_one():
    assert MAX_RETRY == 1


def test_thresholds_match_decisions():
    assert WARN_THRESHOLD == 0.10
    assert HALT_THRESHOLD == 0.25
