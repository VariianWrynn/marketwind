# P2a — Core Triggering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the autonomous triggering layer that wakes the node on a dual-cron schedule, gates on the trading calendar + a per-job freshness window, gathers sources, and drives the existing P1 vertical (Scout pieces → Writer → IM push) end-to-end through `run_once` — publishing a real brief or an honest labeled status, never a stale one.

**Architecture:** `run_once` is the heart: a single coroutine taking **injected seams** (`gather`, `make_body`, IM channels) so all triggering logic is unit-testable offline with fixtures, while the live `__main__`/scheduler wire the real implementations (mirrors the existing `run_writer`/`call_deepseek` pattern). It **reuses** `run_pipeline` for the grounded-floor gate (no second floor). An in-memory APScheduler fires two cron jobs (pre-market = 18:00 ET = US-close+2h, DST-handled by APScheduler's ET timezone; main = 07:00 CST); the calendar gate filters non-trading CST mornings, and a per-job freshness check refuses late runs.

**Tech Stack:** Python 3.11+, APScheduler (AsyncIOScheduler), pytest + pytest-asyncio (mode=AUTO), zoneinfo, asyncpg, Playwright (live only).

---

## Decisions & deferrals recorded by this plan

- **D-P2-1** — Dual-cron *mechanics* land now (both jobs, real DST anchor); **D-19's** 07:00 self-contained content-split + fold marker is **deferred** (phased, not reversed). Recorded in `DECISIONS.md` (Task 10).
- **D-P2-2** — Calendar gates a non-trading day with a **labeled skip status**; **D-20's** degraded news-digest is **deferred**. Recorded in `DECISIONS.md` (Task 10).
- **Design finding** — bot-initiated WeChat keepalive is impossible/unnecessary; proactive delivery rides tokenless home-channel sends.
- **GAP (primary-tracing)** — the live gather builds quotes but cannot set `attached_primary_url` (needs claim_type/company extraction, unbuilt). So the **live floor will not pass yet**; real-delivery is proven via a seeded floor-passing pool. Primary-tracing wiring is a named follow-up (its own brainstorm, before/with P2b). Recorded in `docs/progress/P2a-core-triggering.md` (Task 10).
- **OPEN VERIFICATION (Q5)** — confirm cold tokenless WeChat delivery after the **24h session kill-time** (fire one home-channel send with no prior reply). Lands → unattended push holds; fails → Q5 reopens and WeCom promotes to unattended primary (P2b). Recorded in Task 10.

## What is **out of scope** (→ P2b or later)

Run-ledger + boot-time catch-up · holiday-vs-infra-dead escalation · owner-visible failure pages · transient-retry execution (429/5xx) + non-retryable paging · dead-man's switch · durable both-channels-fail handling · D-19 content split · D-20 digest · primary-tracing wiring · interval/event triggers · persistent job store.

> The startup timing-assertion (Task 8) **reserves** the retry budget (`max_transient_retries × backoff_ceiling_s`) in config now, even though the retry *execution* is P2b — so the inequality stays valid when P2b adds retries.

## File structure

| File | Responsibility |
|---|---|
| `marketwind/config.py` (MOD) | add P2a numeric config (misfire grace, tolerances, ceiling, retry budget) |
| `marketwind/scout/calendar.py` (MOD) | add `is_trading_session(today, sessions)` |
| `marketwind/scout/gather.py` (NEW) | mechanical live gather: `build_pool(...)` (injected seams, offline-testable) + `gather_live(...)` (Playwright/Bocha wiring, live-only) |
| `marketwind/scheduling/anchor.py` (NEW) | pure `anchor_utc(d, hour, minute, tz)` (DST-aware) + `freshness_ok(now, anchor, ...)` |
| `marketwind/scheduling/run_once.py` (NEW) | the heart: calendar+freshness gates → gather → reuse `run_pipeline`; single-flight lock |
| `marketwind/scheduling/trigger.py` (NEW) | `Trigger` Protocol (capped seam) + `CronJob` → APScheduler trigger |
| `marketwind/scheduling/scheduler.py` (NEW) | `assert_timing_safe(...)` + `build_scheduler(...)` (2 jobs, misfire grace) |
| `marketwind/scheduling/__main__.py` (NEW) | manual entrypoint: `--force-calendar` / `--dry-run` / `--send-real` |

---

### Task 0: Setup — branch, dependency, test package

**Files:**
- Modify: `pyproject.toml` (add apscheduler)
- Create: `tests/scheduling/__init__.py` (empty)

- [ ] **Step 1: Create the feature branch**

```bash
git checkout master && git pull --ff-only && git checkout -b p2a-core-triggering
```

- [ ] **Step 2: Add APScheduler dependency**

Add `"apscheduler>=3.10"` to the `[project].dependencies` list in `pyproject.toml`, then install:

```bash
.venv/Scripts/python.exe -m pip install "apscheduler>=3.10"
```

- [ ] **Step 3: Verify the import works**

Run: `.venv/Scripts/python.exe -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; from apscheduler.triggers.cron import CronTrigger; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Create the test package marker**

Create empty `tests/scheduling/__init__.py`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/scheduling/__init__.py
git commit -m "chore(p2a): add apscheduler dep + scheduling test package"
```

---

### Task 1: Config — P2a numeric settings

**Files:**
- Modify: `marketwind/config.py:24` (after `weixin_target`)
- Test: `tests/scheduling/test_config_p2a.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_config_p2a.py
from marketwind.config import Settings


def _settings() -> Settings:
    # database_url / redis_url are required; supply throwaway values.
    return Settings(database_url="postgres://x", redis_url="redis://x")


def test_p2a_defaults_present_and_correct():
    s = _settings()
    assert s.misfire_grace_s == 900
    assert s.max_transient_retries == 2
    assert s.backoff_ceiling_s == 30
    assert s.premarket_tolerance_min == 90
    assert s.main_tolerance_min == 90
    assert s.freshness_ceiling_cst == "10:00"
    assert s.main_report_time_cst == "07:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_config_p2a.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'misfire_grace_s'` (construction-style RED — the field genuinely does not exist; once it does, the `==` assertions are the real check).

- [ ] **Step 3: Add the fields**

In `marketwind/config.py`, immediately after the `weixin_target: str = "weixin"` line and before `model_config`, insert:

```python
    # Triggering (P2a). misfire grace + per-job freshness tolerance (minutes) +
    # absolute freshness ceiling (CST). Retry budget is reserved here for the
    # startup timing assertion; the retry EXECUTION is P2b.
    misfire_grace_s: int = 900
    max_transient_retries: int = 2
    backoff_ceiling_s: int = 30
    premarket_tolerance_min: int = 90
    main_tolerance_min: int = 90
    freshness_ceiling_cst: str = "10:00"
    main_report_time_cst: str = "07:00"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_config_p2a.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add marketwind/config.py tests/scheduling/test_config_p2a.py
git commit -m "feat(p2a): add triggering config (misfire grace, freshness tolerances, retry budget)"
```

---

### Task 2: Calendar — `is_trading_session`

**Files:**
- Modify: `marketwind/scout/calendar.py:19` (after `prev_trading_session`)
- Test: `tests/scheduling/test_calendar_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_calendar_gate.py
from datetime import date

from marketwind.scout.calendar import is_trading_session

_SESSIONS = [date(2026, 6, 5), date(2026, 6, 8), date(2026, 6, 9)]  # Fri, Mon, Tue


def test_trading_day_is_in_session_list():
    assert is_trading_session(date(2026, 6, 8), _SESSIONS) is True


def test_weekend_is_not_a_session():
    assert is_trading_session(date(2026, 6, 6), _SESSIONS) is False  # Saturday
```

- [ ] **Step 2: Run test to verify it fails**

First scaffold a wrong-sentinel stub so the test RUNS and fails on the assertion (not on import). In `marketwind/scout/calendar.py`, add:

```python
def is_trading_session(today: date, sessions: list[date]) -> bool:
    return False  # stub — wrong sentinel so the True-case test fails on assertion
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_calendar_gate.py -v`
Expected: FAIL `test_trading_day_is_in_session_list` with `assert False is True`.

- [ ] **Step 3: Implement**

Replace the stub body with:

```python
def is_trading_session(today: date, sessions: list[date]) -> bool:
    """True iff `today` is one of the known trading sessions."""
    return today in set(sessions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_calendar_gate.py -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/calendar.py tests/scheduling/test_calendar_gate.py
git commit -m "feat(p2a): is_trading_session calendar gate (pure, session-list injected)"
```

---

### Task 3: Anchor — DST-aware `anchor_utc`

**Files:**
- Create: `marketwind/scheduling/anchor.py`
- Test: `tests/scheduling/test_anchor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_anchor.py
from datetime import date, datetime, timezone

from marketwind.scheduling.anchor import anchor_utc


def test_premarket_anchor_is_dst_aware_summer():
    # 18:00 ET (= 16:00 US close + 2h) on a summer date is EDT (UTC-4) -> 22:00 UTC.
    got = anchor_utc(date(2026, 6, 8), 18, 0, "America/New_York")
    assert got == datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)


def test_premarket_anchor_is_dst_aware_winter():
    # 18:00 ET on a winter date is EST (UTC-5) -> 23:00 UTC.
    got = anchor_utc(date(2026, 1, 6), 18, 0, "America/New_York")
    assert got == datetime(2026, 1, 6, 23, 0, tzinfo=timezone.utc)


def test_main_report_anchor_cst():
    # 07:00 CST (UTC+8) -> 23:00 UTC the previous calendar day.
    got = anchor_utc(date(2026, 6, 8), 7, 0, "Asia/Shanghai")
    assert got == datetime(2026, 6, 7, 23, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold a wrong-sentinel stub so the test runs and fails on the assertion. Create `marketwind/scheduling/anchor.py`:

```python
"""Pure scheduling math: DST-aware anchors + per-job freshness."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from marketwind.scout.timeparse import CN_TZ


def anchor_utc(d: date, hour: int, minute: int, tz_name: str) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)  # stub: wrong instant
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_anchor.py -v`
Expected: FAIL `test_premarket_anchor_is_dst_aware_summer` with `assert datetime(2026,6,8,0,0,tzinfo=utc) == datetime(2026,6,8,22,0,tzinfo=utc)`.

- [ ] **Step 3: Implement `anchor_utc`**

Replace the stub body:

```python
def anchor_utc(d: date, hour: int, minute: int, tz_name: str) -> datetime:
    """The UTC instant of `hour:minute` local time on date `d` in `tz_name`.

    zoneinfo resolves the offset for that calendar date, so DST is handled
    automatically (18:00 ET is 22:00 UTC in summer, 23:00 UTC in winter).
    """
    local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=ZoneInfo(tz_name))
    return local.astimezone(timezone.utc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_anchor.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/anchor.py tests/scheduling/test_anchor.py
git commit -m "feat(p2a): DST-aware anchor_utc (US-close+2h ET / 07:00 CST)"
```

---

### Task 4: Freshness — `freshness_ok`

**Files:**
- Modify: `marketwind/scheduling/anchor.py` (add `freshness_ok`)
- Test: `tests/scheduling/test_freshness.py`

The rule (per-job): a run is fresh iff it fired within `tolerance_min` of its own anchor **and** the current CST wall-clock is at/before the absolute ceiling. Lateness is checked first (it's the more specific reason).

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_freshness.py
from datetime import datetime, time, timedelta, timezone

from marketwind.scheduling.anchor import freshness_ok

# Anchor: 22:00 UTC = 06:00 CST next morning (a pre-market fire).
_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_CEIL = time(10, 0)


def test_on_time_run_is_fresh():
    now = _ANCHOR + timedelta(minutes=10)  # 06:10 CST
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=90, ceiling_cst=_CEIL)
    assert fresh is True
    assert reason == "fresh"


def test_late_run_past_tolerance_is_stale():
    now = _ANCHOR + timedelta(minutes=200)  # ~09:20 CST, 200 > 90
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=90, ceiling_cst=_CEIL)
    assert fresh is False
    assert "late" in reason


def test_run_past_absolute_ceiling_is_stale():
    now = _ANCHOR + timedelta(minutes=280)  # ~10:40 CST; big tolerance isolates ceiling
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=600, ceiling_cst=_CEIL)
    assert fresh is False
    assert "ceiling" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold a wrong-sentinel stub. Add to `marketwind/scheduling/anchor.py`:

```python
def freshness_ok(now: datetime, anchor: datetime, *,
                 tolerance_min: int, ceiling_cst: time) -> tuple[bool, str]:
    return False, "stub"  # wrong sentinel so the fresh-case test fails on assertion
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_freshness.py -v`
Expected: FAIL `test_on_time_run_is_fresh` with `assert False is True`.

- [ ] **Step 3: Implement `freshness_ok`**

Replace the stub body:

```python
def freshness_ok(now: datetime, anchor: datetime, *,
                 tolerance_min: int, ceiling_cst: time) -> tuple[bool, str]:
    """(fresh, reason). Late if now is > tolerance_min past anchor; else stale if
    the CST wall-clock is past the absolute ceiling; else fresh."""
    late_by = (now - anchor).total_seconds() / 60.0
    if late_by > tolerance_min:
        return False, f"late: fired {late_by:.0f}min after anchor (tol {tolerance_min})"
    now_cst = now.astimezone(CN_TZ).timetz().replace(tzinfo=None)
    if now_cst > ceiling_cst:
        return False, f"past ceiling {ceiling_cst.strftime('%H:%M')} CST (now {now_cst.strftime('%H:%M')})"
    return True, "fresh"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_freshness.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/anchor.py tests/scheduling/test_freshness.py
git commit -m "feat(p2a): per-job freshness_ok (tolerance + absolute CST ceiling)"
```

---

### Task 5: Gather — mechanical `build_pool`

The control flow (dedup, skip-on-fetch-error, skip-empty-quotes, persist-each) is unit-tested with injected `search`/`fetch_page`/`parse`/`persist` seams. The real `parse` (trafilatura clean + extract) and the live Bocha/Playwright wiring are exercised only in the smoke run, not unit tests.

**Files:**
- Create: `marketwind/scout/gather.py`
- Test: `tests/scheduling/test_gather.py`

> **GAP reminder:** `build_pool` sets `attached_primary_url=None` on every quote (primary-tracing is unbuilt). The live floor will not pass yet — see plan header. Intentional for P2a.

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_gather.py
from datetime import date, datetime, timezone

from marketwind.scout.domain import Quote
from marketwind.scout.gather import build_pool
from marketwind.scout.query import build_recap_queries

_NOW = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_PREV = date(2026, 6, 5)
_QUERIES = build_recap_queries(_PREV)


def _q(text: str) -> Quote:
    return Quote(text=text, span_start=0, span_end=len(text),
                 context_before=None, context_after=None, is_quantitative=False)


def _search_returning(mapping):
    async def _search(query: str):
        return mapping.get(query, [])
    return _search


async def _fetch_ok(url: str) -> str:
    return f"<html>{url}</html>"


def _parse_one_quote(html: str):
    return ("raw:" + html, [_q("一句话。")])


def _persist_recorder(store):
    async def _persist(src):
        store.append(src)
    return _persist


async def test_dedup_same_url_across_queries():
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")],
            _QUERIES[1]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert len(out) == 1
    assert out[0].url == "https://a.cn/x"
    assert len(store) == 1


async def test_fetch_error_is_skipped():
    async def _fetch_boom(url: str) -> str:
        raise RuntimeError("nav failed")
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_boom, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert out == []
    assert store == []


async def test_empty_quotes_is_skipped():
    def _parse_empty(html: str):
        return ("", [])
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_empty,
                           persist=_persist_recorder(store), now=_NOW)
    assert out == []


async def test_kept_source_carries_domain_quotes_and_ingest_ts():
    hits = {_QUERIES[0]: [("https://news.example.cn/p", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert out[0].domain == "news.example.cn"
    assert out[0].publish_ts == _NOW
    assert out[0].raw_content.startswith("raw:")
    assert out[0].quotes[0].attached_primary_url is None
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold a wrong-sentinel stub so the tests run. Create `marketwind/scout/gather.py`:

```python
"""Mechanical Scout gather: queries -> search -> fetch -> parse -> persist.

Control flow is unit-tested with injected seams; the live `gather_live` wiring
(Bocha + Playwright) is smoke-only. NOTE (P2a gap): quotes get
attached_primary_url=None — primary-tracing is unbuilt, so the live floor will
not pass yet; real delivery is proven via a seeded pool.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime

from marketwind.scout.clean import clean_main_content, extract_quotes
from marketwind.scout.domain import Quote, Source
from marketwind.scout.outlets import domain_of
from marketwind.scout.query import build_recap_queries

SearchFn = Callable[[str], Awaitable[list[tuple[str, str]]]]
FetchFn = Callable[[str], Awaitable[str]]
ParseFn = Callable[[str], tuple[str, list[Quote]]]
PersistFn = Callable[[Source], Awaitable[None]]


async def build_pool(*, prev_session: date, search: SearchFn, fetch_page: FetchFn,
                     parse: ParseFn, persist: PersistFn, now: datetime) -> list[Source]:
    return []  # stub — wrong sentinel so dedup/keep tests fail on assertion
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_gather.py -v`
Expected: FAIL `test_dedup_same_url_across_queries` with `assert 0 == 1`; `test_kept_source...` fails on `IndexError`. The two skip tests pass against the stub — fine; the dedup/keep assertions are the discriminating RED.

- [ ] **Step 3: Implement `build_pool` + `default_parse`**

Replace the stub body and add the default parse:

```python
async def build_pool(*, prev_session: date, search: SearchFn, fetch_page: FetchFn,
                     parse: ParseFn, persist: PersistFn, now: datetime) -> list[Source]:
    queries = build_recap_queries(prev_session)
    seen: set[str] = set()
    out: list[Source] = []
    for query in queries:
        for url, _snippet in await search(query):
            if url in seen:
                continue
            seen.add(url)
            try:
                html = await fetch_page(url)
            except Exception:
                continue  # one bad page is skipped, not fatal
            raw, quotes = parse(html)
            if not quotes:
                continue
            src = Source(url=url, domain=domain_of(url), publish_ts=now,
                         raw_content=raw, quotes=quotes)
            await persist(src)
            out.append(src)
    return out


def default_parse(html: str) -> tuple[str, list[Quote]]:
    """Real clean+extract. May raise ValueError on empty extraction (caller skips)."""
    raw = clean_main_content(html)
    return raw, extract_quotes(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_gather.py -v`
Expected: PASS (all 4)

- [ ] **Step 5: Add the live wiring (smoke-only)**

Append to `marketwind/scout/gather.py`:

```python
async def gather_live(conn, *, now: datetime, prev_session: date) -> list[Source]:  # pragma: no cover - live
    """Wire real Bocha search + Playwright fetch + DB persist. Smoke-only."""
    from playwright.async_api import async_playwright

    from marketwind.scout import discover, fetch
    from marketwind.storage.repo import upsert_source

    async def _search(query: str) -> list[tuple[str, str]]:
        return await discover.search(query)

    def _safe_parse(html: str) -> tuple[str, list[Quote]]:
        try:
            return default_parse(html)
        except ValueError:
            return "", []

    async def _persist(src: Source) -> None:
        await upsert_source(conn, src)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context()

        async def _fetch(url: str) -> str:
            return await fetch.fetch_html(context, url)

        try:
            return await build_pool(prev_session=prev_session, search=_search,
                                    fetch_page=_fetch, parse=_safe_parse,
                                    persist=_persist, now=now)
        finally:
            await browser.close()
```

- [ ] **Step 6: Verify the module imports cleanly**

Run: `.venv/Scripts/python.exe -c "import marketwind.scout.gather; print('ok')"`
Expected: prints `ok` (live deps imported lazily inside `gather_live`).

- [ ] **Step 7: Commit**

```bash
git add marketwind/scout/gather.py tests/scheduling/test_gather.py
git commit -m "feat(p2a): mechanical Scout gather (build_pool, injected seams) + live wiring"
```

---

### Task 6: `run_once` — the heart

Reuses `run_pipeline` for the floor gate (no second floor). Gates first (calendar → freshness), so a skip costs **zero** gather/Writer work — `gather` is only awaited when both gates pass. A module-level `asyncio.Lock` serializes concurrent invocations (the cross-job single-flight lock, #4).

**Files:**
- Create: `marketwind/scheduling/run_once.py`
- Test: `tests/scheduling/test_run_once.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_run_once.py
import asyncio
from datetime import date, datetime, time, timedelta, timezone

from marketwind.gateway.im.stub import StubSink
from marketwind.scheduling.run_once import run_once
from marketwind.scout.domain import Quote, Source

_CN = timezone(timedelta(hours=8))
# Anchor 22:00 UTC = 06:00 CST on 2026-06-09; that CST date is the trading day.
_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_NOW_FRESH = _ANCHOR + timedelta(minutes=10)          # 06:10 CST 2026-06-09
_SESSIONS = [date(2026, 6, 8), date(2026, 6, 9)]
_CEIL = time(10, 0)


def _q(text, *, primary=None):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=False, attached_primary_url=primary)


def _passing_sources():
    now = datetime.now(timezone.utc)
    a = Source(url="https://a.cn/x", domain="a.cn", publish_ts=now, raw_content="...",
               quotes=[_q(f"甲{i}") for i in range(4)])
    a.quotes[0] = _q("甲0", primary="https://primary.gov.cn/d")
    b = Source(url="https://b.cn/y", domain="b.cn", publish_ts=now, raw_content="...",
               quotes=[_q(f"乙{i}") for i in range(4)])
    return [a, b]


def _gather_returning(sources, calls):
    async def _gather():
        calls.append(1)
        return sources
    return _gather


def _make_body(awaited):
    async def _mb():
        awaited.append(1)
        return "正文：科创50盘前。"
    return _mb


async def _run(now, *, gather, make_body, primary, fallback, dev, force=False,
               tol=90, anchor=_ANCHOR):
    await run_once(now, sessions=_SESSIONS, anchor=anchor, tolerance_min=tol,
                   ceiling_cst=_CEIL, gather=gather, make_body=make_body,
                   primary=primary, fallback=fallback, dev_channel=dev,
                   trace_id="t", force_calendar=force)


async def test_non_trading_day_skips_before_gather():
    dev, gcalls, awaited = StubSink(), [], []
    sunday = datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)  # CST date 2026-06-08? no
    # 2026-06-07 22:00 UTC = 2026-06-08 06:00 CST (Monday is in sessions) -> use a real non-session
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # -> 2026-06-06 CST (Sat), not in sessions
    await _run(nonsession, gather=_gather_returning([], gcalls),
               make_body=_make_body(awaited), primary=StubSink(),
               fallback=StubSink(), dev=dev, anchor=nonsession)
    assert gcalls == []           # gather never called
    assert awaited == []          # make_body never called
    assert dev.sent and "非交易日" in dev.sent[0]


async def test_stale_run_skips_before_gather():
    dev, gcalls, awaited = StubSink(), [], []
    late = _ANCHOR + timedelta(minutes=200)  # past 90-min tolerance
    await _run(late, gather=_gather_returning([], gcalls),
               make_body=_make_body(awaited), primary=StubSink(),
               fallback=StubSink(), dev=dev)
    assert gcalls == []
    assert awaited == []
    assert dev.sent and "超时" in dev.sent[0]


async def test_above_floor_publishes_dev_labeled_brief():
    primary, awaited, gcalls = StubSink(), [], []
    await _run(_NOW_FRESH, gather=_gather_returning(_passing_sources(), gcalls),
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=StubSink())
    assert gcalls == [1]                                  # gather ran
    assert awaited == [1]                                 # make_body ran
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_sub_floor_routes_status_and_skips_writer():
    dev, primary, awaited, gcalls = StubSink(), StubSink(), [], []
    await _run(_NOW_FRESH, gather=_gather_returning([], gcalls),   # empty pool -> sub-floor
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=dev)
    assert gcalls == [1]                                  # gather ran (needed for floor)
    assert awaited == []                                  # make_body NEVER awaited
    assert primary.sent == []                             # nothing published
    assert dev.sent and "sub-floor" in dev.sent[0]


async def test_force_calendar_runs_on_non_trading_day():
    primary, gcalls, awaited = StubSink(), [], []
    nonsession = datetime(2026, 6, 5, 22, 0, tzinfo=timezone.utc)  # 2026-06-06 CST (Sat)
    await _run(nonsession, gather=_gather_returning(_passing_sources(), gcalls),
               make_body=_make_body(awaited), primary=primary,
               fallback=StubSink(), dev=StubSink(), force=True, anchor=nonsession)
    assert gcalls == [1]                                  # calendar bypassed
    assert primary.sent and primary.sent[0].startswith("【DEV / UNVERIFIED")


async def test_single_flight_serializes_concurrent_runs():
    order = []
    gate = asyncio.Event()

    async def _slow_gather():
        order.append("enter")
        await gate.wait()
        order.append("exit")
        return []

    async def _quick_gather():
        order.append("second-enter")
        return []

    t1 = asyncio.create_task(_run(_NOW_FRESH, gather=_slow_gather,
                                  make_body=_make_body([]), primary=StubSink(),
                                  fallback=StubSink(), dev=StubSink()))
    await asyncio.sleep(0.01)  # let t1 acquire the lock + enter gather
    t2 = asyncio.create_task(_run(_NOW_FRESH, gather=_quick_gather,
                                  make_body=_make_body([]), primary=StubSink(),
                                  fallback=StubSink(), dev=StubSink()))
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(t1, t2)
    # t2's gather must not start until t1 fully exits (lock held).
    assert order == ["enter", "exit", "second-enter"]
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold a stub that returns immediately (no gating, no send). Create `marketwind/scheduling/run_once.py`:

```python
"""run_once: the autonomous single-run heart. Calendar+freshness gates ->
gather -> reuse run_pipeline (floor gate -> label -> push). Single-flight lock."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time

from marketwind.gateway.im.base import IMChannel
from marketwind.orchestration.runner import run_pipeline
from marketwind.scheduling.anchor import freshness_ok
from marketwind.scout.calendar import is_trading_session
from marketwind.scout.domain import Source
from marketwind.scout.timeparse import CN_TZ

_RUN_LOCK = asyncio.Lock()


async def run_once(now: datetime, *, sessions, anchor, tolerance_min, ceiling_cst,
                   gather, make_body, primary, fallback, dev_channel,
                   trace_id, force_calendar=False) -> None:
    return  # stub — no gating, no send: every assertion below fails
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py -v`
Expected: FAIL — `test_non_trading_day_skips_before_gather` with `assert [] and ...` (dev.sent empty), `test_above_floor...` with empty `primary.sent`, etc. Gating/send assertions are the discriminating RED (not import).

- [ ] **Step 3: Implement `run_once`**

Replace the stub body and add the status helpers:

```python
def _nontrading_status(now: datetime, trace_id: str) -> str:
    return f"[MarketWind] {now.astimezone(CN_TZ):%Y-%m-%d} 非交易日，跳过 trace_id={trace_id}"


def _stale_status(reason: str, trace_id: str) -> str:
    return f"[MarketWind] 简报超时跳过 trace_id={trace_id}: {reason}"


async def run_once(now: datetime, *,
                   sessions: list,
                   anchor: datetime,
                   tolerance_min: int,
                   ceiling_cst: time,
                   gather: Callable[[], Awaitable[list[Source]]],
                   make_body: Callable[[], Awaitable[str]],
                   primary: IMChannel,
                   fallback: IMChannel,
                   dev_channel: IMChannel,
                   trace_id: str,
                   force_calendar: bool = False) -> None:
    async with _RUN_LOCK:
        if not force_calendar and not is_trading_session(now.astimezone(CN_TZ).date(), sessions):
            dev_channel.send(_nontrading_status(now, trace_id))
            return
        fresh, reason = freshness_ok(now, anchor, tolerance_min=tolerance_min,
                                     ceiling_cst=ceiling_cst)
        if not fresh:
            dev_channel.send(_stale_status(reason, trace_id))
            return
        sources = await gather()
        await run_pipeline(sources=sources, make_body=make_body,
                           primary=primary, fallback=fallback,
                           dev_channel=dev_channel, trace_id=trace_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_run_once.py -v`
Expected: PASS (all 6)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/run_once.py tests/scheduling/test_run_once.py
git commit -m "feat(p2a): run_once heart — calendar+freshness gates, reuse run_pipeline, single-flight lock"
```

---

### Task 7: Trigger seam (capped) — Protocol + `CronJob`

The project mandates a unified `Trigger` seam (CLAUDE.md §6), but P2a implements **cron only** — no registry, no discovery. A `Trigger` Protocol documents the seam; `CronJob` is the one implementer and converts to an APScheduler trigger. The `interval`/`event` triggers are named in a comment, not built.

**Files:**
- Create: `marketwind/scheduling/trigger.py`
- Test: `tests/scheduling/test_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_trigger.py
from datetime import datetime
from zoneinfo import ZoneInfo

from marketwind.scheduling.trigger import CronJob


def test_cronjob_to_apscheduler_computes_next_fire():
    # Pre-market cron at 18:00 America/New_York. From 17:00 ET, next fire is 18:00 ET.
    job = CronJob(job_id="premarket", hour=18, minute=0, tz="America/New_York")
    trig = job.to_apscheduler()
    ny = ZoneInfo("America/New_York")
    prev = datetime(2026, 6, 8, 17, 0, tzinfo=ny)
    nxt = trig.get_next_fire_time(None, prev)
    assert nxt.hour == 18 and nxt.minute == 0
    assert nxt.tzinfo is not None and nxt.utcoffset() == prev.utcoffset()  # same ET day
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold a stub whose `to_apscheduler` returns a wrong trigger (08:00, not 18:00). Create `marketwind/scheduling/trigger.py`:

```python
"""Unified Trigger seam (CLAUDE.md §6). P2a implements cron ONLY — no registry.

Future implementers (NOT built here): IntervalTrigger (keyword polling),
EventTrigger (Redis Streams -> ConciergeBot, P3). They will satisfy the same
Protocol and register without touching run_once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apscheduler.triggers.cron import CronTrigger


class Trigger(Protocol):
    job_id: str

    def to_apscheduler(self): ...


@dataclass(frozen=True)
class CronJob:
    job_id: str
    hour: int
    minute: int
    tz: str

    def to_apscheduler(self) -> CronTrigger:
        return CronTrigger(hour=8, minute=0, timezone=self.tz)  # stub: wrong hour
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_trigger.py -v`
Expected: FAIL with `assert 8 == 18` (next fire hour wrong).

- [ ] **Step 3: Implement `to_apscheduler`**

Replace the stub return:

```python
    def to_apscheduler(self) -> CronTrigger:
        return CronTrigger(hour=self.hour, minute=self.minute, timezone=self.tz)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_trigger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/trigger.py tests/scheduling/test_trigger.py
git commit -m "feat(p2a): Trigger Protocol + CronJob (cron-only seam, no registry)"
```

---

### Task 8: Scheduler — startup assertion + `build_scheduler`

`assert_timing_safe` enforces the inequality `fire + misfire_grace + retries×backoff < anchor + tolerance` at boot, so a delayed-then-retried run can never do the work and then be killed by freshness (#8). `build_scheduler` registers the two cron jobs with the configured misfire grace.

**Files:**
- Create: `marketwind/scheduling/scheduler.py`
- Test: `tests/scheduling/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_scheduler.py
import pytest

from marketwind.scheduling.scheduler import assert_timing_safe, build_scheduler


def test_timing_safe_passes_with_default_budget():
    # grace 900s (15m) + retries 2*30s (1m) = 16m < 90m tolerance -> OK, no raise.
    assert_timing_safe(misfire_grace_s=900, max_transient_retries=2,
                       backoff_ceiling_s=30, tolerance_min=90)


def test_timing_unsafe_grace_exceeds_tolerance_raises():
    # grace 2h (7200s) alone blows past the 90m tolerance -> must fail loud.
    with pytest.raises(ValueError, match="timing budget"):
        assert_timing_safe(misfire_grace_s=7200, max_transient_retries=2,
                           backoff_ceiling_s=30, tolerance_min=90)


def test_build_scheduler_registers_two_jobs_with_grace():
    async def _job():
        return None
    sched = build_scheduler(run=_job, misfire_grace_s=900)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"premarket", "main"}
    assert jobs["premarket"].misfire_grace_time == 900
    assert jobs["main"].misfire_grace_time == 900
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold stubs: `assert_timing_safe` never raises; `build_scheduler` returns a scheduler with no jobs. Create `marketwind/scheduling/scheduler.py`:

```python
"""In-memory dual-cron scheduler. Recompute fires on boot; no persistent store.
Generous misfire grace; freshness (run_once) is the real stale-guard."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from marketwind.scheduling.trigger import CronJob

_PREMARKET = CronJob(job_id="premarket", hour=18, minute=0, tz="America/New_York")
_MAIN = CronJob(job_id="main", hour=7, minute=0, tz="Asia/Shanghai")


def assert_timing_safe(*, misfire_grace_s, max_transient_retries,
                       backoff_ceiling_s, tolerance_min) -> None:
    return  # stub — never raises


def build_scheduler(*, run: Callable[[], Awaitable[None]], misfire_grace_s: int) -> AsyncIOScheduler:
    return AsyncIOScheduler()  # stub — no jobs registered
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_scheduler.py -v`
Expected: FAIL — `test_timing_unsafe...` (no `ValueError` raised) and `test_build_scheduler...` with `assert set() == {"premarket", "main"}`.

- [ ] **Step 3: Implement**

Replace both stub bodies:

```python
def assert_timing_safe(*, misfire_grace_s: int, max_transient_retries: int,
                       backoff_ceiling_s: int, tolerance_min: int) -> None:
    """Fail loud at boot if a delayed+retried run could outlive its freshness
    tolerance. budget = misfire_grace + retries*backoff (seconds)."""
    budget_s = misfire_grace_s + max_transient_retries * backoff_ceiling_s
    if budget_s >= tolerance_min * 60:
        raise ValueError(
            f"timing budget {budget_s}s >= tolerance {tolerance_min*60}s — "
            "a delayed+retried run would be killed by freshness; "
            "lower misfire_grace_s/retries or raise tolerance"
        )


def build_scheduler(*, run: Callable[[], Awaitable[None]], misfire_grace_s: int) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    for job in (_PREMARKET, _MAIN):
        sched.add_job(run, trigger=job.to_apscheduler(), id=job.job_id,
                      misfire_grace_time=misfire_grace_s, max_instances=1,
                      coalesce=True)
    return sched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_scheduler.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/scheduler.py tests/scheduling/test_scheduler.py
git commit -m "feat(p2a): scheduler — startup timing assertion + dual-cron registration"
```

---

### Task 9: Manual entrypoint — flags → behavior

The CLI runs the **identical** `run_once` path. Two pure resolvers are unit-tested; the live `main()` (real conn/gather/channels) is smoke-only. Per #12, `--force-calendar` **implies dry-run** unless `--send-real` is explicitly passed — forcing the calendar is a test action and must not surprise-push to real WeChat.

**Files:**
- Create: `marketwind/scheduling/__main__.py`
- Test: `tests/scheduling/test_entrypoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/scheduling/test_entrypoint.py
from marketwind.scheduling.__main__ import build_parser, want_real_send


def _parse(argv):
    return build_parser().parse_args(argv)


def test_plain_run_sends_real():
    assert want_real_send(_parse([])) is True


def test_dry_run_never_sends_real():
    assert want_real_send(_parse(["--dry-run"])) is False


def test_force_calendar_implies_dry_run():
    # forcing the calendar without --send-real must NOT do a real send (#12).
    assert want_real_send(_parse(["--force-calendar"])) is False


def test_force_calendar_with_send_real_sends():
    assert want_real_send(_parse(["--force-calendar", "--send-real"])) is True


def test_dry_run_wins_over_send_real():
    assert want_real_send(_parse(["--send-real", "--dry-run"])) is False
```

- [ ] **Step 2: Run test to verify it fails**

Scaffold stubs: a parser with the flags, and `want_real_send` returning a wrong constant. Create `marketwind/scheduling/__main__.py`:

```python
"""Manual entrypoint: run the exact scheduled path by hand.

  python -m marketwind.scheduling.run_once            # real send
  ... --dry-run                                       # route to StubSink
  ... --force-calendar                                # run on a non-trading day (implies --dry-run)
  ... --force-calendar --send-real                    # forced AND real send
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketwind.scheduling.run_once")
    p.add_argument("--force-calendar", action="store_true",
                   help="run even on a non-trading day (implies --dry-run unless --send-real)")
    p.add_argument("--dry-run", action="store_true", help="route sends to StubSink")
    p.add_argument("--send-real", action="store_true",
                   help="with --force-calendar, actually send instead of dry-run")
    return p


def want_real_send(args: argparse.Namespace) -> bool:
    return True  # stub — ignores flags, so dry-run/force tests fail
```

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_entrypoint.py -v`
Expected: FAIL — `test_dry_run_never_sends_real`, `test_force_calendar_implies_dry_run`, `test_dry_run_wins_over_send_real` all `assert True is False`.

- [ ] **Step 3: Implement `want_real_send` + live `main`**

Replace the `want_real_send` stub and add `main`:

```python
def want_real_send(args: argparse.Namespace) -> bool:
    """Real send unless dry-run; --force-calendar defaults to dry-run unless
    --send-real. --dry-run always wins."""
    if args.dry_run:
        return False
    if args.force_calendar and not args.send_real:
        return False
    return True


async def main(argv: list[str] | None = None) -> None:  # pragma: no cover - live
    import asyncio
    from datetime import datetime, time, timezone

    import asyncpg

    from marketwind.config import settings
    from marketwind.gateway.im.factory import build_channels
    from marketwind.gateway.im.stub import StubSink
    from marketwind.scheduling.anchor import anchor_utc
    from marketwind.scheduling.run_once import run_once
    from marketwind.scout.calendar import live_prev_trading_session, _load_sessions
    from marketwind.scout.gather import gather_live

    args = build_parser().parse_args(argv)
    now = datetime.now(timezone.utc)
    sessions = list(_load_sessions())
    prev = live_prev_trading_session(now.date())
    anchor = anchor_utc(now.date(), 18, 0, "America/New_York")  # pre-market anchor

    if want_real_send(args):
        live = settings.model_copy(update={"im_channel": "hermes_weixin"})
        primary, fallback = build_channels(live)
    else:
        primary, fallback = StubSink(), StubSink()
    dev = StubSink()

    conn = await asyncpg.connect(settings.database_url)
    try:
        async def _gather():
            return await gather_live(conn, now=now, prev_session=prev)

        async def _make_body():
            from marketwind.writer.client import call_deepseek
            from marketwind.writer.runner import run_writer
            _id, body = await run_writer(conn, call=call_deepseek)
            return body

        hh, mm = (int(x) for x in settings.freshness_ceiling_cst.split(":"))
        await run_once(now, sessions=sessions, anchor=anchor,
                       tolerance_min=settings.premarket_tolerance_min,
                       ceiling_cst=time(hh, mm), gather=_gather, make_body=_make_body,
                       primary=primary, fallback=fallback, dev_channel=dev,
                       trace_id=f"manual-{now:%Y%m%dT%H%M%S}",
                       force_calendar=args.force_calendar)
    finally:
        await conn.close()


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    asyncio.run(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/scheduling/test_entrypoint.py -v`
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
git add marketwind/scheduling/__main__.py tests/scheduling/test_entrypoint.py
git commit -m "feat(p2a): manual entrypoint — flags resolve channels; force-calendar implies dry-run"
```

---

### Task 10: Record decisions + progress note

No tests (documentation). Records the deferrals the brainstorming locked and the open gaps so a future agent picks them up.

**Files:**
- Modify: `DECISIONS.md` (add D-P2-1, D-P2-2)
- Create: `docs/progress/P2a-core-triggering.md`

- [ ] **Step 1: Add D-P2-1 and D-P2-2 to `DECISIONS.md`**

Under the appropriate section, add two rows (match the existing table format):

```markdown
| D-P2-1 | **Dual-cron mechanics ship in P2a (both jobs, real DST anchor via APScheduler ET cron); D-19's 07:00 self-contained content-split + fold marker is DEFERRED** | phased delivery, not a reversal — the triggering layer is the gating dependency; the content shape is independent and lands later. Consistent with D-18/D-19 |
| D-P2-2 | **Calendar gates a non-trading day with a labeled skip status (to dev channel); D-20's degraded news-digest is DEFERRED** | a labeled skip is honest and cheap; the digest is a content feature, separable from the gate. Consistent with D-20/D-22 |
```

- [ ] **Step 2: Write `docs/progress/P2a-core-triggering.md`**

```markdown
# P2a — Core Triggering

> **Read when:** picking up the triggering/scheduling layer, or before P2b (resilience) / primary-tracing wiring.

**Status:** complete. Branch `p2a-core-triggering`. Plan: `docs/superpowers/plans/2026-06-07-p2a-core-triggering.md`.

**What P2a delivers:** `run_once` (the autonomous single-run heart) wired to an in-memory dual-cron APScheduler. Calendar gate + per-job freshness window decide publish-vs-skip; `run_once` reuses `run_pipeline` for the grounded floor (no second floor). All triggering logic is unit-tested offline via injected `gather`/`make_body`/channel seams; live Bocha/Playwright/DeepSeek/WeChat wiring is smoke-only.

## Modules
| Module | What it does |
|---|---|
| `scout/calendar.py::is_trading_session` | session-list membership gate |
| `scout/gather.py::build_pool` | mechanical gather (dedup/skip/persist), injected seams |
| `scheduling/anchor.py` | DST-aware `anchor_utc` + per-job `freshness_ok` |
| `scheduling/run_once.py` | calendar+freshness gates → gather → run_pipeline; single-flight lock |
| `scheduling/trigger.py` | `Trigger` Protocol + `CronJob` (cron-only seam) |
| `scheduling/scheduler.py` | startup timing assertion + dual-cron registration |
| `scheduling/__main__.py` | manual entrypoint (`--force-calendar`/`--dry-run`/`--send-real`) |

## Invariants proved
- **Gate before work:** non-trading/stale skips cost zero gather/Writer calls (asserted).
- **One floor:** `run_once` reuses `run_pipeline`/`evaluate_floor`.
- **Single-flight:** concurrent runs serialize on a module `asyncio.Lock` (asserted by ordering test).
- **Freshness is per-job + absolute ceiling (10:00 CST).**
- **Timing safety asserted at boot:** `misfire_grace + retries*backoff < tolerance`.
- **force-calendar implies dry-run** unless `--send-real` (#12).

## Open gaps (→ P2b / follow-ups)
- **Primary-tracing wiring (BLOCKER for live floor):** `build_pool` sets `attached_primary_url=None`; the live floor cannot pass until claim_type/company extraction + `trace_to_primary` are wired. Real delivery is proven via a seeded floor-passing pool. Needs its own brainstorm.
- **Q5 cold-delivery verification:** after the 24h session kill-time, fire one tokenless home-channel send with no prior reply. Lands → unattended push holds; fails → WeCom promotes to unattended primary (P2b).
- **P2b resilience:** run-ledger + boot-time catch-up, holiday-vs-infra-dead escalation, owner-visible failure pages, transient-retry execution + non-retryable paging, dead-man's switch, durable both-channels-fail.

## How to test
`.venv/Scripts/python.exe -m pytest tests/scheduling -v` — all offline, no DB/network.
Live smoke (owner-only): `PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling.run_once --force-calendar --send-real` (seed a floor-passing pool first, or expect a sub-floor status until primary-tracing lands).
```

- [ ] **Step 3: Commit**

```bash
git add DECISIONS.md docs/progress/P2a-core-triggering.md
git commit -m "docs(p2a): record D-P2-1/D-P2-2 deferrals + P2a progress note and open gaps"
```

---

## Self-Review

**Spec coverage:** Q1 (run_once wiring) → Tasks 5/6/9; Q2 (dual cron + DST anchor) → Tasks 3/7/8; Q3 (calendar skip+status) → Tasks 2/6; Q4 (Trigger seam, cron-only) → Task 7; Q6 (in-memory + generous grace + freshness) → Tasks 4/6/8; Q8 (manual entrypoint) → Task 9; #4 single-flight → Task 6; #7 per-job freshness → Task 4; #8 startup assertion → Task 8; #12 force-calendar guard → Task 9; #13 concrete numbers → Task 1. Deferrals/gaps → Task 10. **Out of scope** (catch-up, ledger, retries, pages, dead-man, primary-tracing) correctly excluded → P2b.

**Type consistency:** `Source`/`Quote` fields match `domain.py`; `run_pipeline(*, sources, make_body, primary, fallback, dev_channel, trace_id)` matches `orchestration/runner.py`; `build_pool(*, prev_session, search, fetch_page, parse, persist, now)` consistent across Tasks 5/9; `anchor_utc`/`freshness_ok` signatures consistent across Tasks 3/4/6/9; `CronJob.to_apscheduler` consistent across Tasks 7/8; `want_real_send`/`build_parser` consistent across Task 9; `CN_TZ` imported from `scout.timeparse` (not redefined).

**Placeholder scan:** none — every code step shows complete code; every run step shows the exact command + expected RED/GREEN.
