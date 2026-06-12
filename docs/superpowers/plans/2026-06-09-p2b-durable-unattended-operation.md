# P2b — Durable Unattended Operation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dual-cron pipeline survive restarts and transient failures without ever *silently* missing a report — every terminal outcome leaves a durable ledger row and (except a clean publish) a loud owner message over a session-less channel.

**Architecture:** A new `scheduling/dispatch.py` layer sits **above** the existing `run_once`. It resolves each job's own anchor/tolerance (item A), reads/writes a Postgres `run_ledger` (item B), wraps the run in transient-retry (item C), and is the single sender of every owner-visible status message over WeCom-primary (item D). `run_once` and `run_pipeline` are refactored to **return a `RunOutcome`** instead of sending status themselves; the brief publish stays inside `run_pipeline` (preserving the Law-5 commit→publish ordering).

**Tech Stack:** Python 3.11+ (run via `.venv/Scripts/python.exe`), asyncpg + Postgres, APScheduler, pytest (`asyncio_mode="auto"`). DB-backed tests connect via `settings.database_url` and call `apply_migrations` in a fixture (see `tests/verifier/test_record_failures.py`).

---

## Contracts (locked — every task must match these exactly)

**Spec:** `docs/superpowers/specs/2026-06-09-p2b-durable-unattended-operation-design.md`.

**Status constants** (`marketwind/scheduling/outcome.py`) — the seven ledger statuses, as module-level string literals:
```
PUBLISHED        = "published"
SKIPPED_CALENDAR = "skipped_calendar"
SKIPPED_STALE    = "skipped_stale"
SUB_FLOOR        = "sub_floor"
VERIFY_FAIL      = "verify_fail"
MISSED           = "missed"
FAILED_INFRA     = "failed_infra"
```

**`RunOutcome`** (`marketwind/scheduling/outcome.py`) — frozen dataclass: `status: str`, `detail: str | None = None`.

**Repo functions** (`marketwind/storage/repo.py`):
- `async def record_run(conn, *, job_id: str, trading_date: date, status: str, trace_id: str, detail: str | None = None) -> bool` — `insert ... on conflict (job_id, trading_date) do nothing`; returns `True` if a row was inserted, `False` on conflict.
- `async def get_run_status(conn, *, job_id: str, trading_date: date) -> str | None` — the existing row's status, or `None`.

**`run_pipeline`** (`marketwind/orchestration/runner.py`) — new signature, returns `RunOutcome`, **no `dev_channel`**, adds `already_published`:
```
async def run_pipeline(*, sources, draft, judge, record_fail,
                       already_published: Callable[[], Awaitable[bool]],
                       primary, fallback, trace_id) -> RunOutcome
```

**`run_once`** (`marketwind/scheduling/run_once.py`) — new signature, returns `RunOutcome`, **no `dev_channel`**, adds `already_published`:
```
async def run_once(now, *, sessions, anchor, tolerance_min, ceiling_cst,
                   gather, draft, judge, record_fail,
                   already_published: Callable[[], Awaitable[bool]],
                   primary, fallback, trace_id, force_calendar=False) -> RunOutcome
```

**`resolve_job`** + **`JobPlan`** (`marketwind/scheduling/dispatch.py`):
```
@dataclass(frozen=True)
class JobPlan:
    job_id: str
    anchor: datetime
    tolerance_min: int
    ceiling_cst: time
    trading_date: date

def resolve_job(job_id, now, *, premarket_tol_min, main_tol_min, ceiling_cst) -> JobPlan
```

**`dispatch_job`** (`marketwind/scheduling/dispatch.py`):
```
async def dispatch_job(job_id, *, now, conn, sessions, trigger,        # trigger: "cron" | "boot"
                       premarket_tol_min, main_tol_min, ceiling_cst,
                       gather, draft, judge, record_fail,
                       primary, fallback, trace_id,
                       retries, backoff_s) -> RunOutcome
```

**`catch_up`** (`marketwind/scheduling/dispatch.py`):
```
async def catch_up(*, now, conn, sessions, premarket_tol_min, main_tol_min,
                   ceiling_cst, gather, draft, judge, record_fail,
                   primary, fallback, trace_id, retries, backoff_s,
                   window: int = 5) -> list[RunOutcome]
```

**Owner-message literals** (spec-critical substrings; built in `dispatch.py`, preserve existing substrings so no-regression holds):
- `SUB_FLOOR`   → contains `"sub-floor"` and `"brief NOT published"`
- `VERIFY_FAIL` → contains `"verifier gate failed"` and the detail (e.g. `"I3"`)
- `SKIPPED_STALE` → contains `"超时"`
- `SKIPPED_CALENDAR` → heartbeat, prefix `"[MarketWind·heartbeat]"` and contains `"非交易日"`
- `MISSED` → contains `"错过发布窗口"`
- `FAILED_INFRA` → contains `"基础设施失败"`
- `PUBLISHED` → no status message (the brief is the signal)

**Reconciliation note (surface to reviewer):** spec §5 says extend `assert_timing_safe` to sum two retry budgets. Finding #7 removed the send-retry loop (WeCom is session-less; `send_with_fallback` is a single bounded primary→fallback failover, not a loop). So **only one retry loop remains** (upstream, around `run_once`), and the existing single-budget `assert_timing_safe` is already correct. This plan therefore leaves `assert_timing_safe` unchanged (Task 8 documents why). Flag this to the user at handoff.

---

## Task 1: Run-ledger migration

**Files:**
- Create: `migrations/0004_run_ledger.sql`
- Test: `tests/storage/test_run_ledger_schema.py`

- [ ] **Step 1: Write the failing test** (DB-backed; mirror the `conn` fixture in `tests/verifier/test_record_failures.py`)

```python
import asyncpg
import pytest
from datetime import date
from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_unique_job_date_rejects_duplicate(conn):
    await conn.execute("delete from run_ledger where job_id='t-main';")
    await conn.execute(
        "insert into run_ledger (job_id, trading_date, status, trace_id)"
        " values ('t-main', $1, 'published', 'tr1');", date(2026, 6, 9))
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            "insert into run_ledger (job_id, trading_date, status, trace_id)"
            " values ('t-main', $1, 'published', 'tr2');", date(2026, 6, 9))
    await conn.execute("delete from run_ledger where job_id='t-main';")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_run_ledger_schema.py -v`
Expected: FAIL — `UndefinedTableError: relation "run_ledger" does not exist` (table not yet created). This is a legitimate RED: the test asserts a *constraint behavior* and fails because the constrained object is absent; once the table exists without the unique constraint it would fail on the missing `pytest.raises`, so the assertion discriminates.

- [ ] **Step 3: Write the migration**

Create `migrations/0004_run_ledger.sql` with a `create table if not exists run_ledger (...)`: columns `ledger_id uuid primary key default gen_random_uuid()`, `job_id text not null`, `trading_date date not null`, `status text not null`, `trace_id text not null`, `detail text`, `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`, plus `unique (job_id, trading_date)` and an index on `(trading_date)`. Match the SQL style of `migrations/0003_verifier_failures.sql`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_run_ledger_schema.py -v`
Expected: PASS (migration auto-applies via the fixture's `apply_migrations`).

- [ ] **Step 5: Commit**

```bash
git add migrations/0004_run_ledger.sql tests/storage/test_run_ledger_schema.py
git commit -m "feat(p2b): run_ledger table keyed (job_id, trading_date)"
```

---

## Task 2: RunOutcome value object + status constants

**Files:**
- Create: `marketwind/scheduling/outcome.py`
- Test: `tests/scheduling/test_outcome.py`

- [ ] **Step 1: Write the failing test** (pure construction/smoke-import — ImportError RED is legitimate here per CLAUDE.md §8)

```python
from marketwind.scheduling.outcome import (
    RunOutcome, PUBLISHED, SKIPPED_CALENDAR, SKIPPED_STALE,
    SUB_FLOOR, VERIFY_FAIL, MISSED, FAILED_INFRA,
)


def test_constants_are_the_seven_statuses():
    assert {PUBLISHED, SKIPPED_CALENDAR, SKIPPED_STALE, SUB_FLOOR,
            VERIFY_FAIL, MISSED, FAILED_INFRA} == {
        "published", "skipped_calendar", "skipped_stale", "sub_floor",
        "verify_fail", "missed", "failed_infra"}


def test_runoutcome_is_frozen_with_optional_detail():
    o = RunOutcome(status=PUBLISHED)
    assert o.status == "published" and o.detail is None
    o2 = RunOutcome(status=SUB_FLOOR, detail="x")
    assert o2.detail == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_outcome.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'marketwind.scheduling.outcome'`.

- [ ] **Step 3: Write the module**

Create `outcome.py`: the seven `str` constants exactly as above, and `@dataclass(frozen=True) class RunOutcome` with `status: str` and `detail: str | None = None`. No behavior, no I/O.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_outcome.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/outcome.py tests/scheduling/test_outcome.py
git commit -m "feat(p2b): RunOutcome value object + seven status constants"
```

---

## Task 3: Ledger repo functions (record_run, get_run_status)

**Files:**
- Modify: `marketwind/storage/repo.py` (append two functions; add `from datetime import date` import)
- Test: `tests/storage/test_run_ledger_repo.py`

- [ ] **Step 1: Write the failing test** (reuse the `conn` fixture from Task 1's test — copy it into this file)

```python
import asyncpg
import pytest
from datetime import date
from marketwind.config import settings
from marketwind.storage.migrate import apply_migrations
from marketwind.storage.repo import record_run, get_run_status

_D = date(2026, 6, 9)


@pytest.fixture
async def conn():
    c = await asyncpg.connect(settings.database_url)
    await apply_migrations(c)
    try:
        yield c
    finally:
        await c.close()


async def test_record_then_read_status(conn):
    await conn.execute("delete from run_ledger where job_id='r-main';")
    inserted = await record_run(conn, job_id="r-main", trading_date=_D,
                                status="published", trace_id="tr", detail=None)
    assert inserted is True
    assert await get_run_status(conn, job_id="r-main", trading_date=_D) == "published"
    await conn.execute("delete from run_ledger where job_id='r-main';")


async def test_second_record_conflicts_returns_false(conn):
    await conn.execute("delete from run_ledger where job_id='r-dup';")
    assert await record_run(conn, job_id="r-dup", trading_date=_D,
                            status="published", trace_id="a") is True
    assert await record_run(conn, job_id="r-dup", trading_date=_D,
                            status="published", trace_id="b") is False  # on conflict do nothing
    await conn.execute("delete from run_ledger where job_id='r-dup';")


async def test_missing_row_is_none(conn):
    assert await get_run_status(conn, job_id="r-absent", trading_date=_D) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_run_ledger_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'record_run'`. (After adding stubs returning wrong sentinels, re-run to watch the *assertion* fail — `assert inserted is True` on a stub returning `None`.)

- [ ] **Step 3: Write the implementation**

Append to `repo.py`: `record_run` does `insert into run_ledger (job_id, trading_date, status, trace_id, detail) values ($1,$2,$3,$4,$5) on conflict (job_id, trading_date) do nothing returning ledger_id;` via `fetchval`; return `result is not None`. `get_run_status` does `select status from run_ledger where job_id=$1 and trading_date=$2;` via `fetchval`. Match the existing asyncpg style in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/storage/test_run_ledger_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/storage/repo.py tests/storage/test_run_ledger_repo.py
git commit -m "feat(p2b): record_run/get_run_status with on-conflict idempotency"
```

---

## Task 4: Refactor `run_pipeline` to return RunOutcome (drop dev_channel, add check-before-send)

**Files:**
- Modify: `marketwind/orchestration/runner.py`
- Test: `tests/orchestration/` (adapt the existing run_pipeline tests; find them with `ls tests/orchestration/`)

**Why:** `dispatch_job` becomes the single sender of status messages. `run_pipeline` stops calling `dev_channel.send` and instead returns a `RunOutcome`. The brief publish (`send_with_fallback`) stays — it is the product, not a status message — preserving the Law-5 commit→publish ordering. A check-before-send predicate prevents a duplicate publish when another run already recorded `published`.

- [ ] **Step 1: Write/adapt the failing tests**

Adapt the three existing run_pipeline tests (sub-floor, verify-fail, above-floor publishes) to the new return shape, and add a check-before-send test. Key RED assertions (these are the contract — keep verbatim):

```python
# above-floor: still publishes the brief AND returns PUBLISHED
async def test_pass_publishes_and_returns_published(...):
    out = await run_pipeline(sources=..., draft=..., judge=_fake_judge,
                             record_fail=_noop_record, already_published=_never,
                             primary=primary, fallback=StubSink(), trace_id="t")
    assert out.status == "published"
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")

# sub-floor: returns SUB_FLOOR, publishes nothing, does NOT call draft
async def test_sub_floor_returns_outcome_no_publish(...):
    out = await run_pipeline(sources=[], draft=_draft_should_not_run, judge=_fake_judge,
                             record_fail=_noop_record, already_published=_never,
                             primary=primary, fallback=StubSink(), trace_id="t")
    assert out.status == "sub_floor"
    assert primary.sent == []

# verify-fail: returns VERIFY_FAIL with the tripped check in detail, calls record_fail, no publish
async def test_verify_fail_returns_outcome_and_records(...):
    out = await run_pipeline(..., already_published=_never, ...)
    assert out.status == "verify_fail"
    assert "I3" in out.detail
    assert recorded == [("t", <violations>)]   # record_fail still called inside
    assert primary.sent == []

# check-before-send: another run already published -> skip publish, still PUBLISHED
async def test_already_published_skips_send(...):
    async def _already(): return True
    out = await run_pipeline(..., already_published=_already, primary=primary, ...)
    assert out.status == "published"
    assert primary.sent == []          # no duplicate brief
    assert commit_spy["commit_calls"] == 0   # and no second commit
```

where `_never` is `async def _never(): return False`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/orchestration -v`
Expected: FAIL on assertions — `run_pipeline` currently returns `None` (`out.status` → AttributeError on None) and takes `dev_channel`/no `already_published` (TypeError). Since this is a signature change, after updating the signature to a stub returning `RunOutcome(SUB_FLOOR)` for all paths, re-run and watch each `out.status ==` assertion fail for the right reason (retroactive-mutation discipline, CLAUDE.md §8).

- [ ] **Step 3: Implement the refactor**

Rewrite `run_pipeline` per the locked signature. Behavior, in order: floor gate fail → `return RunOutcome(SUB_FLOOR, detail=<the existing _status_message body minus the prefix>)` (no send). Else `bundle = await draft()`; verify; fail → `await record_fail(...)`, `return RunOutcome(VERIFY_FAIL, detail="checks=<sorted checks> (<n> violations)")` (no send). Pass → `if await already_published(): return RunOutcome(PUBLISHED)` (skip commit+publish); else `await bundle.commit()`, `send_with_fallback(apply_label(bundle.body), primary=primary, fallback=fallback, trace_id=trace_id)`, `return RunOutcome(PUBLISHED)`. Delete `_status_message`/`_verify_status` *only if* nothing else imports them (grep first; they may be re-homed to `dispatch.py` in Task 7 — if so, leave them until Task 7 moves them, to keep this task surgical). Keep `send_with_fallback` and its both-channels-fail `RuntimeError` (that propagates up to become `failed_infra` in Task 8).

- [ ] **Step 4: Run to verify pass + no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/orchestration -v`
Expected: PASS. The `send_with_fallback` RuntimeError-on-both-fail behavior must be unchanged (keep/condition any existing test for it).

- [ ] **Step 5: Commit**

```bash
git add marketwind/orchestration/runner.py tests/orchestration/
git commit -m "refactor(p2b): run_pipeline returns RunOutcome; check-before-send guards duplicate publish"
```

---

## Task 5: Refactor `run_once` to return RunOutcome (drop dev_channel, thread already_published)

**Files:**
- Modify: `marketwind/scheduling/run_once.py`
- Test: `tests/scheduling/test_run_once.py` (migrate the 8 existing tests one-to-one)

**Why:** `run_once` stops sending calendar/stale status to `dev_channel` and returns a `RunOutcome` instead; it forwards `already_published`/`primary`/`fallback` to `run_pipeline` and returns the pipeline's outcome. **No-regression constraint:** control flow and gate semantics are unchanged — only the return shape and the removal of the two `dev_channel.send` calls. Every existing assertion migrates one-to-one: a `dev.sent` message assertion becomes a returned-`status` assertion here, and the message-text assertion (e.g. `"非交易日"`, `"超时"`, `"sub-floor"`, `"verifier gate failed"`) moves to the Task 7 dispatch tests.

- [ ] **Step 1: Migrate the failing tests**

Update the shared `_run` helper to drop `dev`/`dev_channel`, add `already_published` (default `async def _never(): return False`), and `return await run_once(...)`. Key RED assertions:

```python
async def test_non_trading_day_returns_skipped_calendar():
    out = await _run(nonsession, gather=_gather_returning([], gcalls),
                     draft=_draft(draft_calls), primary=StubSink(),
                     fallback=StubSink(), anchor=nonsession)
    assert out.status == "skipped_calendar"
    assert gcalls == [] and draft_calls == []      # gather/draft never called (unchanged)

async def test_stale_run_returns_skipped_stale():
    out = await _run(late, gather=_gather_returning([], gcalls), draft=_draft(draft_calls), ...)
    assert out.status == "skipped_stale"
    assert gcalls == [] and draft_calls == []

async def test_above_floor_publishes_and_returns_published():
    out = await _run(_NOW_FRESH, gather=_gather_returning(_passing_sources(), gcalls),
                     draft=_draft(draft_calls), primary=primary, fallback=StubSink())
    assert out.status == "published"
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")

async def test_sub_floor_returns_outcome_and_skips_writer():
    out = await _run(_NOW_FRESH, gather=_gather_returning([], gcalls), draft=_draft(draft_calls), ...)
    assert out.status == "sub_floor"
    assert draft_calls == [] and primary.sent == []

async def test_verify_fail_returns_outcome():
    # i3 bundle
    out = await _run(_NOW_FRESH, gather=_gather_returning(_passing_sources(), []), draft=_d, ...)
    assert out.status == "verify_fail" and "I3" in out.detail
    assert primary.sent == [] and commit_spy["commit_calls"] == 0
```

Keep `test_force_calendar_runs_on_non_trading_day` (assert `out.status == "published"`) and `test_single_flight_serializes_concurrent_runs` (lock behavior unchanged; the helper just returns outcomes).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py -v`
Expected: FAIL — TypeError (signature drops `dev_channel`, adds `already_published`) then, after stubbing the new signature to return `RunOutcome(SKIPPED_CALENDAR)`, the `out.status ==` assertions fail for the right reason (retroactive-mutation discipline).

- [ ] **Step 3: Implement the refactor**

Rewrite `run_once` per the locked signature. Inside the `_RUN_LOCK`: non-trading → `return RunOutcome(SKIPPED_CALENDAR)`; not fresh → `return RunOutcome(SKIPPED_STALE, detail=reason)`; else `sources = await gather()`, `return await run_pipeline(sources=sources, draft=draft, judge=judge, record_fail=record_fail, already_published=already_published, primary=primary, fallback=fallback, trace_id=trace_id)`. Delete `_nontrading_status`/`_stale_status` (their text moves to `dispatch.py` Task 7) and the now-unused `dev_channel` param + `IMChannel` import only if unused. Keep `force_calendar` and the lock exactly as-is.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py -v`
Expected: PASS (all 8 migrated).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/run_once.py tests/scheduling/test_run_once.py
git commit -m "refactor(p2b): run_once returns RunOutcome; status-sending moves to dispatch layer"
```

---

## Task 6: `resolve_job` + `JobPlan` — per-job anchor/tolerance (item A fix)

**Files:**
- Create: `marketwind/scheduling/dispatch.py` (this task adds only `JobPlan` + `resolve_job`; later tasks add `dispatch_job`/`catch_up` to the same file)
- Test: `tests/scheduling/test_resolve_job.py`

**Why (item A):** today both cron jobs are evaluated against the premarket ET anchor, so the 07:00 CST main job is wrongly anchored and `main_tolerance_min` is dead. `resolve_job` gives each job its **own** anchor + tolerance + the trading date the run is for.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, time, timezone
from marketwind.scheduling.dispatch import resolve_job, JobPlan
from marketwind.scout.timeparse import CN_TZ

_NOW = datetime(2026, 6, 9, 22, 30, tzinfo=timezone.utc)   # 06:30 CST 2026-06-10
_CEIL = time(10, 0)


def test_main_uses_its_own_0700_cst_anchor_and_tolerance():
    plan = resolve_job("main", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
    assert isinstance(plan, JobPlan)
    assert plan.job_id == "main"
    assert plan.tolerance_min == 45                       # main's OWN tolerance, not premarket's
    assert plan.trading_date == _NOW.astimezone(CN_TZ).date()
    # 07:00 CST anchor on the trading date:
    assert plan.anchor.astimezone(CN_TZ).hour == 7 and plan.anchor.astimezone(CN_TZ).minute == 0


def test_premarket_uses_et_anchor_and_premarket_tolerance():
    plan = resolve_job("premarket", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
    assert plan.tolerance_min == 90
    # 18:00 America/New_York anchor (US close + reporting offset), per existing premarket behavior:
    from zoneinfo import ZoneInfo
    assert plan.anchor.astimezone(ZoneInfo("America/New_York")).hour == 18


def test_unknown_job_raises():
    import pytest
    with pytest.raises(ValueError):
        resolve_job("nope", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_resolve_job.py -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` (dispatch module absent). Add the `JobPlan` dataclass + a `resolve_job` stub returning a wrong sentinel (e.g. tolerance always 0), re-run, watch `plan.tolerance_min == 45` fail on the assertion.

- [ ] **Step 3: Implement**

In `dispatch.py`: define `JobPlan` (frozen) per the locked contract. `resolve_job` computes `trading_date = now.astimezone(CN_TZ).date()`; for `"main"` → `anchor = anchor_utc(trading_date, 7, 0, "Asia/Shanghai")`, `tolerance_min = main_tol_min`; for `"premarket"` → `anchor = anchor_utc(trading_date, 18, 0, "America/New_York")`, `tolerance_min = premarket_tol_min` (reproduce current premarket anchoring so its tests don't regress); else `raise ValueError(f"unknown job_id: {job_id}")`. Reuse `anchor_utc` from `marketwind.scheduling.anchor`. Return `JobPlan(job_id, anchor, tolerance_min, ceiling_cst, trading_date)`. Pure function, no I/O.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_resolve_job.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_resolve_job.py
git commit -m "feat(p2b): resolve_job gives each job its own anchor+tolerance (item A)"
```

---

## Task 7: `dispatch_job` core — ledger no-op guard, run, single ledger write + single notify

**Files:**
- Modify: `marketwind/scheduling/dispatch.py` (add `dispatch_job` + message builder `_status_text`)
- Test: `tests/scheduling/test_dispatch_job.py`

**Why:** the single entry point both cron and boot call. It reads the ledger (no-op if already terminal), builds the `already_published` closure, calls `run_once`, then — as the **single sender** — writes one ledger row and sends one owner message keyed off the outcome status. (Retry/`failed_infra` is added in Task 8; this task uses a no-retry pass-through so the seams stay small.)

- [ ] **Step 1: Write the failing tests** (stub `run_once` via monkeypatch or an injected seam — see Step 3 note; use a fake conn that records `record_run` calls and answers `get_run_status`)

```python
# already-terminal in ledger -> no-op (run_once never called, no new row, no message)
async def test_existing_terminal_row_is_noop(fake_conn_with_status_published, ...):
    out = await dispatch_job("main", now=_NOW, conn=conn, sessions=_SESSIONS, trigger="cron", ...)
    assert out.status == "published"
    assert run_once_calls == []          # short-circuited
    assert conn.recorded == []           # no duplicate ledger write
    assert primary.sent == []            # published -> no status message

# in-window run -> writes the outcome row AND sends the matching status message
async def test_sub_floor_writes_row_and_sends_status(...):
    out = await dispatch_job("main", ..., trigger="cron", ...)   # run_once stubbed -> RunOutcome(SUB_FLOOR, "g=0 ...")
    assert out.status == "sub_floor"
    assert conn.recorded == [("main", _TD, "sub_floor", "t", "g=0 ...")]
    assert any("sub-floor" in m and "brief NOT published" in m for m in primary.sent)

# boot-trigger relabels a closed-window stale into MISSED
async def test_boot_relabels_stale_to_missed(...):   # run_once stubbed -> RunOutcome(SKIPPED_STALE, "late ...")
    out = await dispatch_job("main", ..., trigger="boot", ...)
    assert out.status == "missed"
    assert conn.recorded[0][2] == "missed"
    assert any("错过发布窗口" in m for m in primary.sent)

# calendar skip -> heartbeat with the distinct prefix
async def test_calendar_skip_sends_distinct_heartbeat(...):   # run_once stubbed -> RunOutcome(SKIPPED_CALENDAR)
    out = await dispatch_job("main", ..., trigger="cron", ...)
    assert out.status == "skipped_calendar"
    assert any(m.startswith("[MarketWind·heartbeat]") and "非交易日" in m for m in primary.sent)

# published -> row written, NO status message
async def test_published_writes_row_no_message(...):   # run_once stubbed -> RunOutcome(PUBLISHED)
    out = await dispatch_job("main", ..., trigger="cron", ...)
    assert conn.recorded[0][2] == "published"
    assert primary.sent == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_dispatch_job.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'dispatch_job'`. Add a stub `dispatch_job` returning `RunOutcome(PUBLISHED)` and ignoring everything; re-run and watch e.g. `conn.recorded == [...]` and the relabel/heartbeat assertions fail for the right reason.

- [ ] **Step 3: Implement**

In `dispatch.py`, `dispatch_job` per the locked signature:
1. `plan = resolve_job(job_id, now, premarket_tol_min=..., main_tol_min=..., ceiling_cst=...)`.
2. `existing = await get_run_status(conn, job_id=job_id, trading_date=plan.trading_date)`; if `existing is not None` → `return RunOutcome(existing)` (no row, no message).
3. Build `async def _already(): return (await get_run_status(conn, job_id=job_id, trading_date=plan.trading_date)) == PUBLISHED`.
4. `outcome = await run_once(now, sessions=sessions, anchor=plan.anchor, tolerance_min=plan.tolerance_min, ceiling_cst=plan.ceiling_cst, gather=gather, draft=draft, judge=judge, record_fail=record_fail, already_published=_already, primary=primary, fallback=fallback, trace_id=trace_id)`. (Task 8 wraps this call in retry; here call it directly.)
5. If `trigger == "boot" and outcome.status == SKIPPED_STALE`: `outcome = RunOutcome(MISSED, detail=outcome.detail)`.
6. `await record_run(conn, job_id=job_id, trading_date=plan.trading_date, status=outcome.status, trace_id=trace_id, detail=outcome.detail)` — the single ledger write.
7. `text = _status_text(outcome, plan, trace_id)`; if `text is not None`: `send_with_fallback(text, primary=primary, fallback=fallback, trace_id=trace_id)` — the single status sender. **Order matters:** record_run BEFORE send so the durable row survives a failed page (finding #3).
8. `return outcome`.

`_status_text(outcome, plan, trace_id) -> str | None` builds the message per the locked **Owner-message literals** table (PUBLISHED → `None`; SKIPPED_CALENDAR → `f"[MarketWind·heartbeat] {plan.trading_date} 非交易日，跳过 trace_id={trace_id}"`; SKIPPED_STALE → `f"[MarketWind] 简报超时跳过 trace_id={trace_id}: {outcome.detail}"`; SUB_FLOOR → `f"[MarketWind] sub-floor shortfall trace_id={trace_id} {outcome.detail} — brief NOT published"`; VERIFY_FAIL → `f"[MarketWind] verifier gate failed trace_id={trace_id} {outcome.detail} — brief NOT published"`; MISSED → `f"[MarketWind] 错过发布窗口（节点离线）trace_id={trace_id}: {outcome.detail}"`; FAILED_INFRA → `f"[MarketWind] ⚠ 基础设施失败，重试耗尽 trace_id={trace_id}: {outcome.detail}"`).

**Testability seam note:** so tests can stub `run_once`, import it as `from marketwind.scheduling import run_once as run_once_mod` and call `run_once_mod.run_once(...)`, OR accept `run_once` is monkeypatched at `marketwind.scheduling.dispatch.run_once`. Pick the monkeypatch-at-dispatch approach (simplest): `from marketwind.scheduling.run_once import run_once` and tests do `monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", _stub)`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_dispatch_job.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_dispatch_job.py
git commit -m "feat(p2b): dispatch_job single-sender; ledger no-op guard; boot stale->missed relabel"
```

---

## Task 8: Transient-retry + `failed_infra` escalation (item C, hybrid)

**Files:**
- Modify: `marketwind/scheduling/dispatch.py` (wrap the `run_once` call in Task 7 step 4 with a retry loop; add `_TRANSIENT` classifier)
- Test: `tests/scheduling/test_dispatch_retry.py`

**Why (item C):** transient infra errors (gather/DeepSeek/Postgres, and the both-channels-down `RuntimeError` from `send_with_fallback`) retry with backoff; on exhaustion → `failed_infra` + loud page. Terminal gated outcomes (`sub_floor`/`verify_fail`) are NOT retried (they are returned outcomes, not exceptions). Per finding #7 there is **no** separate send-retry loop — `send_with_fallback` already does one bounded primary→fallback failover.

- [ ] **Step 1: Write the failing tests** (inject a `run_once` stub that raises N times then succeeds, using `backoff_s=0` to keep tests instant)

```python
async def test_transient_then_success_retries(...):
    calls = {"n": 0}
    async def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("boom")
        return RunOutcome(PUBLISHED)
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", _flaky)
    out = await dispatch_job("main", ..., trigger="cron", retries=2, backoff_s=0, ...)
    assert out.status == "published" and calls["n"] == 2

async def test_exhausted_retries_become_failed_infra_and_page(...):
    async def _always(*a, **k): raise TimeoutError("down")
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", _always)
    out = await dispatch_job("main", ..., trigger="cron", retries=2, backoff_s=0, ...)
    assert out.status == "failed_infra"
    assert conn.recorded[0][2] == "failed_infra"           # durable row written
    assert any("基础设施失败" in m for m in primary.sent)    # loud page

async def test_unknown_error_is_not_silently_retried(...):
    calls = {"n": 0}
    async def _boom(*a, **k):
        calls["n"] += 1
        raise KeyError("programming bug")                  # NOT in the transient set
    monkeypatch.setattr("marketwind.scheduling.dispatch.run_once", _boom)
    out = await dispatch_job("main", ..., trigger="cron", retries=2, backoff_s=0, ...)
    assert out.status == "failed_infra" and calls["n"] == 1  # no retry spin on an unknown error
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_dispatch_retry.py -v`
Expected: FAIL — current `dispatch_job` calls `run_once` once and lets the exception propagate (no `failed_infra` mapping). `out.status == "failed_infra"` fails.

- [ ] **Step 3: Implement**

Add `_TRANSIENT = (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError, RuntimeError)` and (if available cheaply) `asyncpg.PostgresConnectionError` — keep the tuple curated and documented; `RuntimeError` is included because `send_with_fallback` raises it when both channels fail. Wrap the Task-7 step-4 `run_once` call: loop up to `retries + 1` attempts; on a `_TRANSIENT` exception, if attempts remain `await asyncio.sleep(backoff_s)` and retry; else set `outcome = RunOutcome(FAILED_INFRA, detail=f"{type(e).__name__}: {e}")` and break. On any **non**-`_TRANSIENT` exception, immediately set `outcome = RunOutcome(FAILED_INFRA, detail=...)` and break (no retry — fail closed loudly, finding's transient-boundary rule). Then continue to the (unchanged) Task-7 relabel → `record_run` → `_status_text` send path, so `failed_infra` gets its durable row and loud page exactly like other statuses.

**`assert_timing_safe` — leave unchanged.** Add a one-line comment in `dispatch.py` near the retry loop documenting the reconciliation: only one retry loop exists (this one); the send failover is bounded and loop-free (finding #7), so the existing single-budget `assert_timing_safe(misfire_grace_s, max_transient_retries, backoff_ceiling_s, tolerance_min)` in `scheduler.py` already bounds it. Do not edit `scheduler.py` here.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_dispatch_retry.py tests/scheduling/test_dispatch_job.py -v`
Expected: PASS (retry tests green; Task 7 tests still green — non-throwing paths unaffected).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_dispatch_retry.py
git commit -m "feat(p2b): transient-retry + failed_infra escalation; unknown errors fail closed"
```

---

## Task 9: Boot-time catch-up with backward reconciliation (item B, finding #2)

**Files:**
- Modify: `marketwind/scheduling/dispatch.py` (add `catch_up`)
- Test: `tests/scheduling/test_catch_up.py`

**Why:** on boot, before cron registration, reconcile the last `window` (5) trading dates so a multi-day outage produces a `missed` row **per absent day**, not one misleading row. Today, in-window + no row → run inline; today, window closed → `missed`; any **past** trading date with no row → `missed` (never re-run a long-closed window).

- [ ] **Step 1: Write the failing tests** (fake conn answering `get_run_status`/recording `record_run`; stub `dispatch_job` to observe today-delegation)

```python
# past trading dates with no row -> one `missed` row each, never run
async def test_absent_past_days_each_get_missed(...):
    # sessions = last 5 trading dates incl today; ledger empty
    outs = await catch_up(now=_NOW, conn=conn, sessions=_FIVE_SESSIONS, ..., window=5)
    missed_dates = [r for r in conn.recorded if r[2] == "missed"]
    assert len(missed_dates) >= 4 * 2          # 4 past dates x 2 jobs, all missed
    assert dispatch_job_calls_for_today >= 1   # today still delegated to dispatch_job

# a date already terminal in the ledger is skipped (idempotent)
async def test_existing_rows_not_overwritten(...):
    # pre-seed get_run_status -> "published" for (main, past_date)
    outs = await catch_up(...)
    assert ("main", past_date, "missed", ...) not in conn.recorded

# bound respected: older-than-window gaps are NOT reconciled
async def test_only_last_5_sessions_considered(...):
    outs = await catch_up(now=_NOW, conn=conn, sessions=_SEVEN_SESSIONS, ..., window=5)
    reconciled_dates = {r[1] for r in conn.recorded}
    assert _SEVEN_SESSIONS[0] not in reconciled_dates   # the 6th/7th-oldest untouched
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_catch_up.py -v`
Expected: FAIL — `catch_up` absent (`AttributeError`). Stub it to return `[]` doing nothing; re-run, watch `len(missed_dates) >= 8` fail.

- [ ] **Step 3: Implement**

`catch_up` per the locked signature. Compute `today = now.astimezone(CN_TZ).date()`. Take the last `window` trading dates from `sessions` that are `<= today` (sort, slice). For each `(job_id in ("premarket", "main"), d in those dates)`:
- `if await get_run_status(conn, job_id=job_id, trading_date=d) is not None`: skip (idempotent).
- `elif d == today`: `outcome = await dispatch_job(job_id, now=now, conn=conn, sessions=sessions, trigger="boot", premarket_tol_min=..., main_tol_min=..., ceiling_cst=..., gather=gather, draft=draft, judge=judge, record_fail=record_fail, primary=primary, fallback=fallback, trace_id=trace_id, retries=retries, backoff_s=backoff_s)` (in-window runs; closed-window → dispatch's boot relabel makes it `missed`).
- `else` (past date, no row): `await record_run(conn, job_id=job_id, trading_date=d, status=MISSED, trace_id=trace_id, detail="boot reconcile: window closed unrun")`, then `send_with_fallback(_status_text(RunOutcome(MISSED, ...), <a JobPlan for d>, trace_id), ...)`, append `RunOutcome(MISSED)`. (Build a minimal `JobPlan` for the past date via `resolve_job(job_id, <midnight CST of d as datetime>, ...)` or inline the missed message — keep it simple; the message must contain `"错过发布窗口"`.)
Return the list of outcomes.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_catch_up.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/dispatch.py tests/scheduling/test_catch_up.py
git commit -m "feat(p2b): boot catch-up reconciles last 5 trading dates (missed row per absent day)"
```

---

## Task 10: Channel factory flip — WeCom-webhook is the unattended primary (item D)

**Files:**
- Modify: `marketwind/gateway/im/factory.py`
- Test: `tests/gateway/test_factory_channels.py` (find existing factory tests first with `ls tests/gateway/`; add to them)

**Why (item D):** the unattended push channel must be session-less. WeCom-webhook has no session to go stale; hermes/WeChat is the warm two-way ConciergeBot channel and the fallback.

- [ ] **Step 1: Write the failing test**

```python
from marketwind.gateway.im.factory import build_channels
from marketwind.gateway.im.wecom_webhook import WecomWebhook
from marketwind.gateway.im.hermes_weixin import HermesWeixin


def _settings(**kw):
    from marketwind.config import Settings
    base = dict(database_url="postgres://x", redis_url="redis://x",
                wecom_webhook_url="https://qyapi.weixin.qq.com/x")
    base.update(kw)
    return Settings(**base)


def test_wecom_webhook_channel_is_wecom_primary_hermes_fallback():
    primary, fallback = build_channels(_settings(im_channel="wecom_webhook"))
    assert isinstance(primary, WecomWebhook)
    assert isinstance(fallback, HermesWeixin)     # was StubSink before; now the warm channel
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/gateway/test_factory_channels.py -v`
Expected: FAIL — current `wecom_webhook` branch returns `(WecomWebhook(...), StubSink())`; `isinstance(fallback, HermesWeixin)` fails.

- [ ] **Step 3: Implement**

In the `wecom_webhook` branch of `build_channels`, set `fallback = HermesWeixin(hermes_bin=settings.hermes_bin, target=settings.weixin_target)` instead of `StubSink()`. Leave the `stub` and `hermes_weixin` branches unchanged (surgical). The live unattended entrypoint (Task 11) selects `im_channel="wecom_webhook"`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/gateway/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marketwind/gateway/im/factory.py tests/gateway/test_factory_channels.py
git commit -m "feat(p2b): wecom_webhook channel = WeCom primary + hermes fallback (item D)"
```

---

## Task 11: Wire the scheduler + boot to per-job dispatch (item A wiring + boot catch-up)

**Files:**
- Modify: `marketwind/scheduling/scheduler.py` (`build_scheduler` registers each job against its own `dispatch(job_id)` closure)
- Modify: `marketwind/scheduling/__main__.py` (boot: run `catch_up`, then register cron via `build_scheduler`; select `wecom_webhook`)
- Test: `tests/scheduling/test_scheduler.py` (extend existing; find with `ls tests/scheduling/`)

**Why:** close item A at the wiring level (each job fires with its own `job_id` so `dispatch_job`/`resolve_job` pick the right anchor) and run boot catch-up before steady-state cron. The `__main__` live wiring is `# pragma: no cover` (exercised only by the manual scheduled-path run).

- [ ] **Step 1: Write the failing test** (scheduler-level, offline — assert each job is registered with its own job_id arg)

```python
import asyncio
from marketwind.scheduling.scheduler import build_scheduler


def test_each_job_registered_with_its_own_job_id():
    seen = []
    async def _dispatch(job_id): seen.append(job_id)
    sched = build_scheduler(dispatch=_dispatch, misfire_grace_s=900)
    jobs = sched.get_jobs()
    ids = {j.id for j in jobs}
    assert ids == {"premarket", "main"}
    # each job's args carry its own job_id (so dispatch resolves the right anchor):
    arg_ids = {j.args[0] for j in jobs}
    assert arg_ids == {"premarket", "main"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_scheduler.py -v`
Expected: FAIL — current `build_scheduler` takes `run` (parameterless) and registers both jobs against it with no `args`; `j.args[0]` raises `IndexError` / the `dispatch=` kwarg is unknown (TypeError). Update the signature first, then watch `arg_ids == {...}` discriminate.

- [ ] **Step 3: Implement**

Change `build_scheduler` to `build_scheduler(*, dispatch: Callable[[str], Awaitable[None]], misfire_grace_s: int)`. For each `job in (_PREMARKET, _MAIN)`: `sched.add_job(dispatch, args=[job.job_id], trigger=job.to_apscheduler(), id=job.job_id, misfire_grace_time=misfire_grace_s, max_instances=1, coalesce=True)`. Leave `assert_timing_safe` and the `_PREMARKET`/`_MAIN` definitions unchanged.

In `__main__.py` (all under the existing `# pragma: no cover` live path): build `conn`; select channels via `settings.model_copy(update={"im_channel": "wecom_webhook"})` + `build_channels(...)`; define `async def _dispatch(job_id): await dispatch_job(job_id, now=datetime.now(timezone.utc), conn=conn, sessions=sessions, trigger="cron", premarket_tol_min=settings.premarket_tolerance_min, main_tol_min=settings.main_tolerance_min, ceiling_cst=<parsed freshness_ceiling_cst>, gather=_gather, draft=_draft, judge=call_judge, record_fail=_record_fail, primary=primary, fallback=fallback, trace_id=f"cron-{job_id}-{...}", retries=settings.max_transient_retries, backoff_s=settings.backoff_ceiling_s)`. On boot, before `sched.start()`, `await catch_up(now=..., conn=conn, sessions=sessions, ...same args..., trigger handled internally, window=5)`. Then `sched = build_scheduler(dispatch=_dispatch, misfire_grace_s=settings.misfire_grace_s)` and start. Keep `assert_timing_safe(...)` called at boot as today.

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling -v`
then the full suite: `.venv/Scripts/python.exe -m pytest tests/verifier tests/orchestration tests/scheduling tests/writer tests/storage tests/gateway -v`
Expected: PASS across the board (no regressions).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/scheduler.py marketwind/scheduling/__main__.py tests/scheduling/test_scheduler.py
git commit -m "feat(p2b): per-job dispatch wiring + boot catch-up before cron (item A wiring)"
```

---

## Task 12: Progress note

**Files:**
- Create: `docs/progress/P2b-durable-unattended.md`

- [ ] **Step 1: Write the note** (lightweight, mirror `docs/progress/verifier-law5-gate.md`)

A table (module · what it does · commit) covering: `0004_run_ledger.sql`, `outcome.py`, `record_run`/`get_run_status`, `run_pipeline` refactor, `run_once` refactor, `resolve_job`, `dispatch_job`, retry/`failed_infra`, `catch_up`, factory flip, scheduler/boot wiring. Then bullet the invariants proved: unique `(job_id, trading_date)` = double-publish guard; single-sender (dispatch) for all status; at-least-once send/record seam (send-then-record + check-before-send); per-job anchors (item A); backward reconciliation (finding #2); fail-closed transient boundary (finding #7 reconciliation re `assert_timing_safe` left unchanged). Close with the four deferred gaps from spec §8 and the residual silent-miss window from spec §1/§6 (closed only by the deferred dead-man's switch).

- [ ] **Step 2: Commit**

```bash
git add docs/progress/P2b-durable-unattended.md
git commit -m "docs(p2b): progress note for durable unattended operation"
```

---

## Final verification (after all tasks)

- [ ] Run the full offline suite and confirm green:

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all pass. Then dispatch a final code-reviewer over the whole branch before finishing.
