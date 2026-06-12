"""Tests for dispatch_job (Task 7 P2b).

Stubs:
  - run_once  monkeypatched at marketwind.scheduling.dispatch.run_once
  - record_run / get_run_status monkeypatched at marketwind.scheduling.dispatch.*
  - StubSink for primary/fallback IM channels
"""
from __future__ import annotations

import pytest
from datetime import datetime, time, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.dispatch import dispatch_job
from marketwind.scheduling.outcome import (
    RunOutcome,
    PUBLISHED,
    SKIPPED_CALENDAR,
    SKIPPED_STALE,
    SUB_FLOOR,
    VERIFY_FAIL,
    MISSED,
    FAILED_INFRA,
)
from marketwind.scout.timeparse import CN_TZ

# ---------------------------------------------------------------------------
# Fixed test fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 9, 22, 30, tzinfo=timezone.utc)
_TD = _NOW.astimezone(CN_TZ).date()
_SESSIONS = []  # not used since run_once is monkeypatched

_COMMON_KWARGS = dict(
    now=_NOW,
    conn=None,  # repo fns are monkeypatched, so the real conn is never touched
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
    retries=0,
    backoff_s=0,
)


# ---------------------------------------------------------------------------
# Helpers: fake async record_run / get_run_status backed by a dict
# ---------------------------------------------------------------------------

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
# Test 1: existing terminal row → no-op (no run_once, no row, no message)
# ---------------------------------------------------------------------------

async def test_existing_terminal_row_is_noop(monkeypatch):
    run_once_calls = []

    async def stub_run_once(*args, **kwargs):
        run_once_calls.append(kwargs)
        return RunOutcome(PUBLISHED)

    _, recorded, fake_get, fake_record = _make_ledger(
        pre_seeded={("main", _TD): "published"}
    )

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)

    primary = StubSink()
    fallback = StubSink()

    out = await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "primary": primary, "fallback": fallback},
    )

    assert out.status == "published"
    assert run_once_calls == []          # short-circuited
    assert recorded == []                # no duplicate ledger write
    assert primary.sent == []            # published -> no status message


# ---------------------------------------------------------------------------
# Test 2: sub_floor → row written AND status message sent
# ---------------------------------------------------------------------------

async def test_sub_floor_writes_row_and_sends_status(monkeypatch):
    async def stub_run_once(*args, **kwargs):
        return RunOutcome(SUB_FLOOR, "g=0 p=0 o=0")

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

    assert out.status == "sub_floor"
    assert recorded == [("main", _TD, "sub_floor", "t", "g=0 p=0 o=0")]
    assert any("sub-floor" in m and "brief NOT published" in m for m in primary.sent)


# ---------------------------------------------------------------------------
# Test 3: boot trigger + SKIPPED_STALE → relabeled to MISSED
# ---------------------------------------------------------------------------

async def test_boot_relabels_stale_to_missed(monkeypatch):
    async def stub_run_once(*args, **kwargs):
        return RunOutcome(SKIPPED_STALE, "late 45min")

    _, recorded, fake_get, fake_record = _make_ledger()

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)

    primary = StubSink()
    fallback = StubSink()

    out = await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "trigger": "boot", "primary": primary, "fallback": fallback},
    )

    assert out.status == "missed"
    assert recorded[0][2] == "missed"
    assert any("错过发布窗口" in m for m in primary.sent)


# ---------------------------------------------------------------------------
# Test 4: calendar skip → heartbeat with distinct prefix
# ---------------------------------------------------------------------------

async def test_calendar_skip_sends_distinct_heartbeat(monkeypatch):
    async def stub_run_once(*args, **kwargs):
        return RunOutcome(SKIPPED_CALENDAR)

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

    assert out.status == "skipped_calendar"
    assert recorded[0][2] == "skipped_calendar"  # calendar skips still write a ledger row
    assert any(
        m.startswith("[MarketWind·heartbeat]") and "非交易日" in m
        for m in primary.sent
    )


# ---------------------------------------------------------------------------
# Test 5: published → row written, NO status message
# ---------------------------------------------------------------------------

async def test_published_writes_row_no_message(monkeypatch):
    async def stub_run_once(*args, **kwargs):
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

    assert recorded[0][2] == "published"
    assert primary.sent == []


# ---------------------------------------------------------------------------
# Test 6: record-then-send — the ledger row is written BEFORE any message
#         (durability seam: a row must survive a failed page)
# ---------------------------------------------------------------------------

async def test_records_before_sending(monkeypatch):
    events: list[str] = []

    async def stub_run_once(*args, **kwargs):
        return RunOutcome(SUB_FLOOR, "g=0 p=0 o=0")

    ledger, _, fake_get, _ = _make_ledger()

    async def recording_record(conn, *, job_id, trading_date, status, trace_id, detail=None):
        events.append("record")
        ledger[(job_id, trading_date)] = status
        return True

    def recording_send(text, *, primary, fallback, trace_id):
        events.append("send")

    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", stub_run_once)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", recording_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.send_with_fallback", recording_send)

    await dispatch_job(
        "main",
        **{**_COMMON_KWARGS, "primary": StubSink(), "fallback": StubSink()},
    )

    assert events == ["record", "send"]
