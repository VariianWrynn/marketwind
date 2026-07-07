"""Tests for catch_up boot-time backward reconciliation (Task 9 P2b).

Harness style mirrors test_dispatch_retry.py:
  - _make_ledger() returns (ledger, recorded, fake_get_run_status, fake_record_run)
  - monkeypatch marketwind.scheduling.dispatch.get_run_status / .record_run / .dispatch_job
  - StubSink for primary/fallback
  - backoff_s=0
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.dispatch import catch_up
from marketwind.scheduling.outcome import RunOutcome, PUBLISHED, MISSED
from marketwind.scout.timeparse import CN_TZ

# ---------------------------------------------------------------------------
# Fixed test fixtures
# ---------------------------------------------------------------------------

# "now" resolves to Wednesday 2026-06-10 06:30 CST — well into the trading day.
_NOW = datetime(2026, 6, 9, 22, 30, tzinfo=timezone.utc)  # 2026-06-10 06:30 CST
_TODAY = _NOW.astimezone(CN_TZ).date()  # 2026-06-10

# Five genuine weekday trading sessions: today + 4 prior (the 06-06/06-07 weekend
# is skipped, as a real trading calendar would).
# 06-04 (Thu), 06-05 (Fri), 06-08 (Mon), 06-09 (Tue), 06-10 (Wed, today)
_SESSIONS_5 = [
    date(2026, 6, 4),
    date(2026, 6, 5),
    date(2026, 6, 8),
    date(2026, 6, 9),
    date(2026, 6, 10),
]

# Seven genuine weekday trading sessions: today + 6 prior (for the window-bound test).
# 06-02 (Tue), 06-03 (Wed), 06-04 (Thu), 06-05 (Fri), 06-08 (Mon), 06-09 (Tue), 06-10 (Wed)
_SESSIONS_7 = [
    date(2026, 6, 2),
    date(2026, 6, 3),
    date(2026, 6, 4),
    date(2026, 6, 5),
    date(2026, 6, 8),
    date(2026, 6, 9),
    date(2026, 6, 10),
]

_COMMON_KWARGS = dict(
    now=_NOW,
    conn=None,
    premarket_tol_min=90,
    main_tol_min=90,
    ceiling_cst=time(10, 0),
    gather=None,
    draft=None,
    judge=None,
    record_fail=None,
    trace_id="test-trace",
    retries=0,
    backoff_s=0,
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
# Test 1: absent past days each get a missed row; today delegated to dispatch_job
# ---------------------------------------------------------------------------

async def test_absent_past_days_each_get_missed(monkeypatch):
    """Empty ledger, 5-session list including today.

    After catch_up:
    - The past 4 dates × 2 jobs = 8 missed rows recorded.
    - dispatch_job was called for today at least once.
    - At least one owner page contains '错过发布窗口'.
    """
    _, recorded, fake_get, fake_record = _make_ledger()

    dispatch_calls: list = []

    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        dispatch_calls.append((job_id, now, trigger))
        return RunOutcome(PUBLISHED)

    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)

    primary = StubSink()
    fallback = StubSink()

    outcomes = await catch_up(
        sessions=_SESSIONS_5,
        primary=primary,
        fallback=fallback,
        **_COMMON_KWARGS,
    )

    missed = [r for r in recorded if r[2] == "missed"]
    assert len(missed) >= 8, (
        f"expected >= 8 missed rows (4 past dates × 2 jobs), got {len(missed)}: {missed}"
    )

    assert len(dispatch_calls) >= 1, (
        f"expected dispatch_job called for today, but dispatch_calls={dispatch_calls!r}"
    )

    owner_pages = primary.sent + fallback.sent
    assert any("错过发布窗口" in m for m in owner_pages), (
        f"expected at least one owner page with '错过发布窗口', got pages={owner_pages!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: existing rows are not overwritten (idempotent skip)
# ---------------------------------------------------------------------------

async def test_existing_rows_not_overwritten(monkeypatch):
    """Pre-seed ledger with published for (main, 2026-06-09).

    After catch_up, no missed row for that specific (job, date) should appear.
    """
    pre_seeded = {("main", date(2026, 6, 9)): "published"}
    _, recorded, fake_get, fake_record = _make_ledger(pre_seeded)

    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        return RunOutcome(PUBLISHED)

    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)

    primary = StubSink()
    fallback = StubSink()

    await catch_up(
        sessions=_SESSIONS_5,
        primary=primary,
        fallback=fallback,
        **_COMMON_KWARGS,
    )

    # The pre-seeded row should not have a missed entry added
    missed_for_main_june9 = [
        r for r in recorded
        if r[0] == "main" and r[1] == date(2026, 6, 9) and r[2] == "missed"
    ]
    assert len(missed_for_main_june9) == 0, (
        f"expected no missed row for (main, 2026-06-09) because it was pre-seeded as published; "
        f"got {missed_for_main_june9!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: only last `window` sessions are considered (oldest 2 ignored)
# ---------------------------------------------------------------------------

async def test_only_last_5_sessions_considered(monkeypatch):
    """Pass a 7-session list and window=5.

    After catch_up, the oldest 2 dates (2026-06-02 and 2026-06-03) must NOT
    appear in the recorded rows.
    """
    _, recorded, fake_get, fake_record = _make_ledger()

    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        return RunOutcome(PUBLISHED)

    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)

    primary = StubSink()
    fallback = StubSink()

    await catch_up(
        sessions=_SESSIONS_7,
        primary=primary,
        fallback=fallback,
        window=5,
        **_COMMON_KWARGS,
    )

    recorded_dates = {r[1] for r in recorded}
    out_of_window = {date(2026, 6, 2), date(2026, 6, 3)}
    in_recorded = recorded_dates & out_of_window
    assert len(in_recorded) == 0, (
        f"expected oldest 2 dates to be outside window and untouched; "
        f"but found {in_recorded} in recorded dates {recorded_dates!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: today already has a ledger row → not re-dispatched, no new row
# ---------------------------------------------------------------------------

async def test_today_already_recorded_is_not_redispatched(monkeypatch):
    """Pre-seed both jobs for today as published.

    catch_up must skip today via the idempotent guard: dispatch_job is never
    called and no row is written for today.
    """
    pre_seeded = {
        ("premarket", _TODAY): "published",
        ("main", _TODAY): "published",
    }
    _, recorded, fake_get, fake_record = _make_ledger(pre_seeded)

    dispatch_calls: list = []

    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        dispatch_calls.append(job_id)
        return RunOutcome(PUBLISHED)

    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)

    await catch_up(
        sessions=_SESSIONS_5,
        primary=StubSink(),
        fallback=StubSink(),
        **_COMMON_KWARGS,
    )

    assert dispatch_calls == [], (
        f"expected no dispatch for an already-recorded today; got {dispatch_calls!r}"
    )
    today_rows = [r for r in recorded if r[1] == _TODAY]
    assert today_rows == [], f"expected no new row for today; got {today_rows!r}"


async def test_today_delegation_routes_per_job_url(monkeypatch):
    """premarket-today delegates with the premarket URL; main-today with the main URL."""
    _, _, fake_get, fake_record = _make_ledger()
    seen = {}
    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        seen[job_id] = kwargs.get("healthcheck_url")
        return RunOutcome(PUBLISHED)
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)
    await catch_up(
        sessions=_SESSIONS_5, primary=StubSink(), fallback=StubSink(),
        healthcheck_urls={"premarket": "http://hc/pre", "main": "http://hc/main"},
        **_COMMON_KWARGS,
    )
    assert seen == {"premarket": "http://hc/pre", "main": "http://hc/main"}


async def test_past_missed_does_not_ping(monkeypatch):
    pings = []
    _, recorded, fake_get, fake_record = _make_ledger()
    async def stub_dispatch_job(job_id, *, now, conn, sessions, trigger, **kwargs):
        return RunOutcome(PUBLISHED)  # today path stubbed; not under test here
    monkeypatch.setattr("marketwind.scheduling.dispatch.get_run_status", fake_get)
    monkeypatch.setattr("marketwind.scheduling.dispatch.record_run", fake_record)
    monkeypatch.setattr("marketwind.scheduling.dispatch.dispatch_job", stub_dispatch_job)
    monkeypatch.setattr("marketwind.scheduling.dispatch.check_in", lambda url: pings.append(url))
    await catch_up(
        sessions=_SESSIONS_5, primary=StubSink(), fallback=StubSink(),
        healthcheck_urls={"premarket": "http://hc/pre", "main": "http://hc/main"},
        **_COMMON_KWARGS,
    )
    # 4 past dates x 2 jobs = 8 missed rows written directly by catch_up — none pinged.
    assert [r for r in recorded if r[2] == "missed"], "sanity: past missed rows were written"
    assert pings == [], f"past missed reconciliation must not ping; got {pings!r}"
