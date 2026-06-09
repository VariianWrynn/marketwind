# P2b — Durable Unattended Operation: design

> **Read when:** picking up P2b work, or before changing anything in the scheduling / dispatch / run-ledger layer.

**Status:** design approved (2026-06-09 brainstorm). Scope **A + B + C + D**; dead-man's switch (E) deferred.

**Goal:** make the dual-cron pipeline survive restarts and transient failures without ever *silently* missing or degrading a report — every terminal outcome leaves a durable ledger row and, except for a clean publish, an owner-visible message over a durable channel.

**Through-line — "Obvious fail welcomed, silent fail strongly un-welcomed."** Every design choice below favors a loud, owner-visible signal over the cheapest silent handling. The only silent terminal state is a clean `published` (the brief itself is the signal) — and even a non-trading day emits a lightweight heartbeat.

---

## 1. Problem & scope

The P2a triggering layer fires a dual cron in-memory (APScheduler). Four gaps make it unsafe for unattended operation:

- **A — Wrong anchor for the main job.** `build_scheduler` registers both jobs against one parameterless `run`, so the 07:00 CST main job is evaluated against the *premarket* (US-close+2h ET) anchor. `main_report_time_cst` / `main_tolerance_min` are dead config. This is a correctness bug.
- **B — No durable memory.** Jobs live only in memory. A restart that overlaps a fire window silently drops that run — no record, no notice.
- **C — No retry / no escalation.** A transient gather/LLM/Postgres/send failure ends the run with nothing distinguishing "infra blip" from "correctly refused to publish."
- **D — Channel can go stale.** The unattended push channel (hermes/WeChat) fails `ret=-2` (a mislabeled stale-session, not rate-limit) after ~24h with no warm session.

**In scope:** A (per-job anchor/tolerance dispatch), B (run ledger + boot catch-up), C (transient-retry + escalation), D (WeCom-webhook as durable unattended primary).

**Out of scope (deferred gaps):** see §8.

---

## 2. Architecture (Approach 1 — thin dispatch layer above `run_once`)

A new `scheduling/dispatch.py` owns *whether/when* a job runs and records the outcome. The existing `run_once` keeps owning *the run* (the gated pipeline). Both cron and boot-catch-up call the **same** `dispatch_job` entry point — there is exactly one code path that fires a job.

```
cron fire ─┐
           ├─► dispatch_job(job_id, now, …) ─► run_once(…) ─► run_pipeline (floor→draft→verify→commit→send)
boot ──────┘        │
                    └─ resolves anchor/tolerance · reads+writes ledger · retry · sends owner message
```

**Clean split of responsibilities:**
- `dispatch_job` — per-job anchor/tolerance, ledger read/write, calendar/freshness/late decisions, retry wrapping, and the **single** place every owner-visible message is sent.
- `run_once` — single-flight lock + calendar/freshness gating + gather + pipeline. Refactored to **return a structured outcome** instead of `None` and instead of sending its own status messages.
- `run_pipeline` — unchanged (the Law-5 gate from Part A).

Rejected alternatives: folding the ledger/retry into `run_once` (turns it into a kitchen sink, couples the pipeline to persistence, against focused-file guidance); a `JobRunner` class per job (OO ceremony for N=2 jobs differing only by anchor+tolerance — YAGNI).

---

## 3. The run ledger (item B)

One durable Postgres table; one row per job-run. Its unique key doubles as the double-publish guard.

**Columns:** `job_id` (`'premarket'`|`'main'`), `trading_date` (the CST trading date the run is *for*), `status` (one of the seven below), `trace_id`, `detail` (short text for loud statuses; null otherwise), `created_at`, `updated_at`.

**`UNIQUE (job_id, trading_date)`** is the keystone: at most one terminal row per job per trading date. A second `published` insert for the same key fails → double-publish is structurally impossible, even if cron and boot-catch-up race.

**Seven terminal statuses and owner notification:**

| status | meaning | owner message |
|---|---|---|
| `published` | brief sent | none — the brief is the signal |
| `skipped_calendar` | non-trading day | lightweight heartbeat |
| `skipped_stale` | cron woke past freshness window | loud status |
| `sub_floor` | floor gate: insufficient sources | loud status |
| `verify_fail` | Verifier gate tripped | loud status |
| `missed` | node down through whole window, caught at boot | loud late notice |
| `failed_infra` | transient retries exhausted | loud page |

**Deliberately omitted (simplicity):** no `running`/`started` intermediate state — `_RUN_LOCK` already serializes, and a half-written run simply has no terminal row and is re-evaluated at next boot. No separate idempotency table — the unique constraint *is* the idempotency. No per-attempt retry log — `failed_infra` + `detail` is enough to page on.

**Migration:** one new `migrations/0004_run_ledger.sql`, auto-applied by the existing filename-ordered migrate globber. No change to existing tables.

---

## 4. Dispatch flow (items A + B)

`dispatch_job(job_id, *, now, …)` runs, in order:

1. **Resolve the job's own anchor + tolerance** (item A fix). premarket → US-close+2h ET anchor; main → 07:00 CST anchor. The resolved anchor fixes the *trading date* the run is for. The main job stops borrowing the premarket anchor.
2. **Read the ledger** for `(job_id, trading_date)`. Terminal row already present → no-op, return. (Makes boot-catch-up idempotent.)
3. **Calendar gate.** Non-trading day → write `skipped_calendar`, send heartbeat, return.
4. **Freshness gate (the late path).** Past anchor+tolerance:
   - reached by **cron** → `skipped_stale`, loud status.
   - reached at **boot** with no prior row and window already closed → `missed`, loud late notice.
5. **In-window → run.** Call `run_once` wrapped in the retry unit (§5). Map its structured outcome → terminal ledger row + matching owner message: `published` / `sub_floor` / `verify_fail` / `failed_infra`.

**`run_once` refactor (no-regression constraint).** Only its *return shape* changes (`None` → structured outcome); control flow and gate semantics are unchanged. Status-sending moves up to `dispatch_job` so there is one sender (no double-send, no split). All existing `run_once` tests stay green — each StubSink assertion is migrated one-to-one to the dispatch layer or re-pointed at the returned outcome; the sub-floor / verify-fail / stale behaviors are preserved bit-for-bit.

---

## 5. Retry & escalation (item C — hybrid)

**Three outcome classes:**
1. **Terminal gated outcomes** (`sub_floor`, `verify_fail`) — correct refusals, **never retried**; loud status + ledger row.
2. **Transient infra errors** — connection errors, timeouts, 5xx from gather (Bocha/Playwright), DeepSeek (writer/judge), Postgres, and the known `ret=-2` stale-session send error — **retried with backoff**.
3. **Retry-exhausted** → `failed_infra`, **loud page**.

**Hybrid placement (Option 3):**
- **One retry unit wraps the upstream pipeline** (gather → floor → draft → verify) as a single block — re-running gather is cheap/idempotent, no partial-state bookkeeping.
- **A dedicated send-with-retry** at the send step, because `ret=-2` is the one failure mode actually observed. Per the web-search finding, `ret=-2` is a mislabeled stale session — the retry **refreshes/retries the session (and fails over primary→fallback)**, it does not sleep-and-wait. Reuses the existing `send_with_fallback` path.

**Transient boundary fails closed.** Only a curated set (connection errors, timeouts, 5xx, `ret=-2`) is treated as transient and retried. Anything unrecognized is **not** silently retried — it surfaces as `failed_infra` and pages. (Obvious-fail applied to the retry boundary itself.)

**Budget is bounded by existing safety.** Retries live inside the freshness window: `assert_timing_safe(misfire_grace, max_retries, backoff_ceiling, tolerance)` already guarantees `misfire_grace + retries×backoff < tolerance`, so retry can never push a publish past freshness. Retry config reuses that assertion; no new timing knobs. No generic "retry any exception" wrapper, no circuit-breaker, no jitter library (a bounded loop under the existing assertion suffices for a single-node personal system).

---

## 6. Status & channel mechanics (item D)

- **One WeCom-webhook channel** carries the brief *and* every status/heartbeat/page message — the durable, session-less channel. `hermes_weixin` stays as fallback + the warm two-way ConciergeBot channel. A separate alert channel is rejected: it would rely on the very session that goes stale when a page is most needed.
- **`dispatch_job` is the single sender** — every owner-visible message derives from the terminal outcome in one place.
- **Messages** are short, self-labeling, `trace_id`-stamped, one per status; loud ones carry `detail`. `skipped_calendar` → terse heartbeat; `published` → no status. Exact literal strings are spec-critical and pinned at plan time.
- **Factory flip:** `gateway/im/factory.py` unattended path resolves primary = WeCom-webhook, fallback = hermes_weixin (today reversed).

---

## 7. Boot-time catch-up (item B)

At startup, **before** registering cron: iterate both jobs, call the same `dispatch_job` for today's trading date.
- Already-terminal in ledger → no-op (idempotent).
- In-window + no row → runs inline now.
- Window closed + no row → `missed` + loud late notice.

Then register cron normally. Steady-state this is a no-op; it acts only after a restart overlapping a fire window. The unique `(job_id, trading_date)` constraint guards the cron-vs-catch-up race.

---

## 8. Out of scope — deferred gaps (recorded, not silently dropped)

1. **Dead-man's switch (item E)** — an out-of-process watcher that pages if the node itself is dead (can't self-report). Deferred: needs a second process, borders the "cut Watchdog complexity" guidance.
2. **Clawbot session-warmth warning** — warn the owner over WeCom if the hermes/WeChat ConciergeBot session wasn't warmed in the last 24h; sent ~8h after the morning report (same day), over the durable channel.
3. **Calendar-skip content posting** — replace the bare heartbeat with a useful "markets closed today, here's the week ahead" note on non-trading days.
4. **Per-attempt retry forensics** — currently only `failed_infra` + `detail`; no per-attempt log. Add if debugging ever needs it.

---

## 9. Testing strategy

All offline, no live network/DB beyond the existing test Postgres.
- **Ledger:** unique-constraint rejects a second `published` for one `(job, date)`; each status round-trips.
- **Dispatch:** per-job anchor resolution (main uses its own anchor, not premarket); calendar skip → heartbeat + `skipped_calendar`; cron-late → `skipped_stale`; in-window → runs and maps outcome to row+message; already-terminal → no-op.
- **`run_once` refactor:** all 8 existing tests green against the new return shape; sub-floor/verify-fail/stale behavior unchanged (assertions migrated one-to-one).
- **Retry:** curated transient error retries then succeeds; unrecognized error → `failed_infra` (no silent retry); exhausted budget → `failed_infra` + page; send `ret=-2` → session-refresh retry then fallback.
- **Catch-up:** boot with no row in-window → runs; window closed → `missed` + notice; already `published` → no-op; cron-vs-catch-up race → second insert rejected, no double-publish.

RED discipline per CLAUDE.md §8: assertion-level RED required; signature-change tasks use the retroactive mutation check.
