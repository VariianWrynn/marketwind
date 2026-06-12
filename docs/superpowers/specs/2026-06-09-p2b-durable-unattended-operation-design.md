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

**What this does and does NOT close (read before trusting the ledger).** B + boot-catch-up converts **"down across a fire window, then recovered"** into a loud, owner-visible signal. It does **nothing** for **"down and staying down"**: a node dead for three days never boots, never runs catch-up, and emits zero signal for those three days. The silent-miss class is therefore *narrowed*, not eliminated — it shrinks to "the node is down across a fire window **and has not yet rebooted**." Closing that residual requires an out-of-process, pull-based watcher (the dead-man's switch, §8.1) — deliberately deferred. Likewise, every owner notification here is **push-based** over a channel; if the push channel itself is down, the page cannot escape (see §6) and the durable ledger row is the only record until reboot. A reader must not believe the silent-miss class is fully closed — it is narrowed to a stated residual window.

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
| `missed` | window closed unrun, caught at boot (today's closed window, or any absent past day in the reconciliation window) | loud late notice |
| `failed_infra` | transient retries exhausted | loud page |

**Deliberately omitted (simplicity):** no `running`/`started` intermediate state — `_RUN_LOCK` already serializes, and a half-written run simply has no terminal row and is re-evaluated at next boot. No separate idempotency table — the unique constraint *is* the idempotency. No per-attempt retry log — `failed_infra` + `detail` is enough to page on.

**Delivery semantics: at-least-once, by deliberate choice (the send/record seam).** A brief send (network side-effect) and the `published` row write (DB) cannot be made exactly-once together. Two orderings, two failure modes if the process crashes between them:
- *record-then-send*, crash between → a `published` row exists but **no brief was ever delivered**. A silent miss — catastrophic by our ethos.
- *send-then-record*, crash between → next boot finds no row, re-runs, and **delivers a duplicate brief**. Obvious and harmless.

We choose **send-then-record (at-least-once)**: a rare duplicate report is an *obvious* fail; a phantom `published` row is a *silent* one. To shrink the duplicate window from "whole run" to "a few milliseconds," the send step does a **check-before-send**: immediately before sending, re-query `(job_id, trading_date)`; if a `published` row already exists, skip the send. The `UNIQUE` constraint still guards the row insert; the check-before-send guards the duplicate delivery. The residual window (crash *between* the check and the row write) is accepted and named, not papered over as exactly-once.

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
2. **Transient infra errors** — connection errors, timeouts, 5xx from gather (Bocha/Playwright), DeepSeek (writer/judge), and Postgres — **retried with backoff**.
3. **Retry-exhausted** → `failed_infra`, **loud page**.

**Hybrid placement (Option 3):**
- **One retry unit wraps the upstream pipeline** (gather → floor → draft → verify) as a single block — re-running gather is cheap/idempotent, no partial-state bookkeeping.
- **A dedicated send step** uses the existing `send_with_fallback` primary→fallback path. WeCom-webhook (primary, §6) is session-less and cannot go stale; the hermes fallback's `ret=-2` staleness is *not* worth a refresh dance — it is simply a **failed fallback**. So `ret=-2` is **not** in the curated transient-retry set: if WeCom fails *and* the hermes fallback returns `ret=-2`, both channels are down → `failed_infra` + page. (This drops the formerly-planned session-refresh retry as near-dead code now that the primary is session-less — a deliberate simplification.)

**Transient boundary fails closed.** Only a curated set (connection errors, timeouts, 5xx from gather/DeepSeek/Postgres) is treated as transient and retried. Anything unrecognized is **not** silently retried — it surfaces as `failed_infra` and pages. (Obvious-fail applied to the retry boundary itself.)

**Budget is bounded by existing safety — both retry sites summed.** Retries live inside the freshness window. The safety inequality must bound the **total** elapsed across *both* retry sites, not each independently: `misfire_grace + (upstream_retries × upstream_backoff) + (send_retries × send_backoff) < tolerance`. `assert_timing_safe` is extended/parameterized so its single check covers the summed budget; if the combined budget would exceed `tolerance`, it raises at startup rather than letting a run publish past freshness. No new runtime timing knobs beyond what that one assertion validates. No generic "retry any exception" wrapper, no circuit-breaker, no jitter library (a bounded loop under the assertion suffices for a single-node personal system).

---

## 6. Status & channel mechanics (item D)

- **One WeCom-webhook channel** carries the brief *and* every status/heartbeat/page message — the durable, session-less channel. `hermes_weixin` stays as fallback + the warm two-way ConciergeBot channel. A separate alert channel is rejected: it would rely on the very session that goes stale when a page is most needed.
- **`dispatch_job` is the single sender** — every owner-visible message derives from the terminal outcome in one place.
- **Messages** are short, self-labeling, `trace_id`-stamped, one per status; loud ones carry `detail`. `skipped_calendar` → terse heartbeat; `published` → no status. Exact literal strings are spec-critical and pinned at plan time.
- **Heartbeat must not train the owner to mute the channel (#8).** The `skipped_calendar` heartbeat is the only *routine* daily message and shares the channel that carries real pages. It MUST be visually distinct from loud statuses — a dedicated low-noise prefix (e.g. a `·` / "heartbeat" marker) separable from the page prefix — so weekend/holiday heartbeats can be filtered *without* filtering pages. A channel muted because it cried wolf on weekends is a silent fail by another route. (Heartbeat *suppression/batching* is a tuning knob; the visual-distinctness requirement is mandatory.)
- **When the push channel itself is down (#3 — the page rides a possibly-failed channel).** A `failed_infra` page is pushed over WeCom, but `failed_infra` can be *caused by* WeCom being down. There is no push-based escape from a dead push channel. The contract on a send failure is therefore best-effort + durable record: (1) attempt primary (WeCom), then (2) fallback (hermes); (3) **always** write the `failed_infra` ledger row (the durable record of record, independent of any channel); (4) the process exits non-zero so a supervisor/log is a second out-of-band signal. **What the owner actually observes when *both* channels are down:** nothing pushed — only the ledger row + non-zero exit + logs — until the deferred pull-based dead-man's switch (§8.1) reads that state externally. This residual is the §1 "down push channel" window, stated here so the failure mode is named, not silent-by-omission.
- **Factory flip:** `gateway/im/factory.py` unattended path resolves primary = WeCom-webhook, fallback = hermes_weixin (today reversed).

---

## 7. Boot-time catch-up (item B)

At startup, **before** registering cron, **reconcile a bounded backward window** — the last **5 trading dates** (not just today) — for both jobs (#2). For each (job, trading_date) in that window:
- Already-terminal in ledger → no-op (idempotent).
- **Today, in-window + no row** → runs inline now.
- **Today, window closed + no row** → `missed` + loud late notice.
- **A *past* trading date with no row** → write `missed` (never re-run a stale date — the window is long closed) and surface it. A multi-day outage thus produces a `missed` row **per absent day**, not a single misleading one-day `missed`. Without this, a Mon–Wed outage that boots Wed night would leave Mon/Tue as *absent* rows — the ledger would look authoritative while silently under-reporting. Backward reconciliation keeps the ledger's "no row" from masquerading as "nothing happened."

The 5-date bound is deliberate (not unbounded history): it covers a long-weekend-plus-outage without scanning the whole table; older gaps are accepted (a week-long outage is the dead-man's-switch's job, §8.1).

Then register cron normally. Steady-state this is a no-op; it acts only after a restart overlapping a fire window.

**The ledger prevents double-*delivery*, not double-*work* (#6).** Boot catch-up runs inline *before* cron registration, and `_RUN_LOCK` is in-memory (per-process) — it does not exist across a rapid crash-restart loop. Two restarts can therefore each do the expensive gather→draft→verify (real LLM spend) before one loses the `published` insert race; the `UNIQUE (job_id, trading_date)` constraint guarantees only one *delivery*, not one *run*. For a single-node personal system this wasted work is tolerable and explicitly accepted; eliminating it would need a DB-level advisory lock claimed before the run, which is out of scope here.

---

## 8. Out of scope — deferred gaps (recorded, not silently dropped)

1. **Dead-man's switch (item E)** — an out-of-process, **pull-based** watcher that pages if the node itself is dead or the push channel is down (cases an in-process push design *fundamentally cannot* self-report). This is the exact closure for the two residual windows named in §1 and §6: "down and staying down" (no boot → no catch-up) and "push channel itself down" (no push can escape). Deferred: needs a second process, borders the "cut Watchdog complexity" guidance — but it is the *only* thing that closes those residuals, so it is the highest-value next item, not a nice-to-have.
2. **Clawbot session-warmth warning** — warn the owner over WeCom if the hermes/WeChat ConciergeBot session wasn't warmed in the last 24h; sent ~8h after the morning report (same day), over the durable channel.
3. **Calendar-skip content posting** — replace the bare heartbeat with a useful "markets closed today, here's the week ahead" note on non-trading days.
4. **Per-attempt retry forensics** — currently only `failed_infra` + `detail`; no per-attempt log. Add if debugging ever needs it.

---

## 9. Testing strategy

All offline, no live network/DB beyond the existing test Postgres.
- **Ledger:** unique-constraint rejects a second `published` for one `(job, date)`; each status round-trips.
- **Dispatch:** per-job anchor resolution (main uses its own anchor, not premarket); calendar skip → heartbeat + `skipped_calendar`; cron-late → `skipped_stale`; in-window → runs and maps outcome to row+message; already-terminal → no-op.
- **`run_once` refactor:** all 8 existing tests green against the new return shape; sub-floor/verify-fail/stale behavior unchanged (assertions migrated one-to-one).
- **Retry:** curated transient error retries then succeeds; unrecognized error → `failed_infra` (no silent retry); exhausted budget → `failed_infra` + page; combined upstream+send budget exceeding tolerance → `assert_timing_safe` raises at startup; WeCom fail + hermes `ret=-2` (both channels down) → `failed_infra` + ledger row written + non-zero exit (no `ret=-2` refresh retry).
- **Catch-up:** boot with no row in-window → runs; window closed today → `missed` + notice; already `published` → no-op; **past trading date absent → `missed` written per absent day across the 5-date window** (not one misleading row); cron-vs-catch-up race → second insert rejected, no double-publish.
- **Delivery seam:** check-before-send skips a send when a `published` row already exists (duplicate-window shrink); send-then-record ordering verified (a crash-simulated "no row yet" re-runs and delivers rather than recording a phantom publish).
- **Heartbeat distinctness:** `skipped_calendar` message carries the low-noise heartbeat prefix, distinct from the loud-status/page prefix.

RED discipline per CLAUDE.md §8: assertion-level RED required; signature-change tasks use the retroactive mutation check.
