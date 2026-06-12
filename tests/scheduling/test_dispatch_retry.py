"""Tests for transient-retry + failed_infra escalation in dispatch_job (Task 8 P2b).

Mirrors the harness style of test_dispatch_job.py:
  - _NOW, _TD, _COMMON_KWARGS, _make_ledger() replicated here for self-containment
  - run_once / get_run_status / record_run monkeypatched at marketwind.scheduling.dispatch.*
  - StubSink for primary/fallback IM channels
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.dispatch import dispatch_job
from marketwind.scheduling.outcome import (
    RunOutcome,
    PUBLISHED,
    FAILED_INFRA,
)
from marketwind.scout.timeparse import CN_TZ

# ---------------------------------------------------------------------------
# Fixed test fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 9, 22, 30, tzinfo=timezone.utc)
_TD = _NOW.astimezone(CN_TZ).date()
_SESSIONS = []

_COMMON_KWARGS = dict(
    now=_NOW,
    conn=None,
    sessions=_SESSIONS,
    trigger="cron",
    premarket_tol_min=90,
    main_tol_min=90,
    ceiling_cst=time(10, 0),
    gather=None,
    draft=None,
    judge=None,
    record_fail=None,
    primary=None,
    fallback=None,
    trace_id="t",
    retries=2,
    backoff_s=0,  # instant — no real sleeping in tests
)


def _make_ledger(pre_seeded: dict | None = None):
    """Return (ledger_dict, recorded_list, async get_run_status fn, async record_run fn)."""
    ledger: dict = dict(pre_seeded or {})
    recorded: list = []

    async def fake_get_run_status(conn, *, job_id, trading_date):
        return ledger.get((job_id, trading_date))

    async def fake_record_run(conn, *, job_id, trading_date, status, trace_id, detail=None):
        recorded.append((job_id, trading_date, status, trace_id, detail))
        ledger[(job_id, trading_date)] = status
        return True

    return ledger, recorded, fake_get_run_status, fake_record_run


# ---------------------------------------------------------------------------
# Test 1: transient error then success → retries and returns published
# ---------------------------------------------------------------------------

async def test_transient_then_success_retries(monkeypatch):
    """run_once raises ConnectionError once, then succeeds; dispatch_job should
    return published and have called run_once exactly 2 times."""
    call_count = 0

    async def stub_run_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("network blip")
        return RunOutcome(PUBLISHED)

    _, recorded, fake_get, fake_record = _make_ledger()

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)

    primary = StubSink()
    fallback = StubSink()

    out = await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "primary": primary, "fallback": fallback},
    )

    assert out.status == "published", f"expected published, got {out.status!r}"
    assert call_count == 2, f"expected 2 calls, got {call_count}"


# ---------------------------------------------------------------------------
# Test 2: all retries exhausted → failed_infra written to ledger + owner page
# ---------------------------------------------------------------------------

async def test_exhausted_retries_become_failed_infra_and_page(monkeypatch):
    """run_once always raises TimeoutError; with retries=2 (3 total attempts)
    dispatch_job should return failed_infra, write it to the ledger, and
    send a message containing '基础设施失败'."""

    async def stub_run_once(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    _, recorded, fake_get, fake_record = _make_ledger()

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)

    primary = StubSink()
    fallback = StubSink()

    out = await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "primary": primary, "fallback": fallback, "retries": 2},
    )

    assert out.status == "failed_infra", f"expected failed_infra, got {out.status!r}"
    assert recorded, "expected a ledger row to be written"
    assert recorded[0][2] == "failed_infra", (
        f"expected ledger row status 'failed_infra', got {recorded[0][2]!r}"
    )
    assert any("基础设施失败" in m for m in primary.sent), (
        f"expected '基础设施失败' in owner page, got primary.sent={primary.sent!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: unknown (non-transient) error → failed_infra immediately, no retry
# ---------------------------------------------------------------------------

async def test_unknown_error_is_not_silently_retried(monkeypatch):
    """run_once raises KeyError (NOT in _TRANSIENT); dispatch_job should return
    failed_infra and call run_once exactly once — no retry spin."""
    call_count = 0

    async def stub_run_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise KeyError("missing key in data")

    _, recorded, fake_get, fake_record = _make_ledger()

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)

    primary = StubSink()
    fallback = StubSink()

    out = await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "primary": primary, "fallback": fallback, "retries": 2},
    )

    assert out.status == "failed_infra", f"expected failed_infra, got {out.status!r}"
    assert call_count == 1, (
        f"expected exactly 1 call (no retry on unknown error), got {call_count}"
    )
