# P2b — durable, unattended operation (A + B + C + D)

> **Read when:** picking up scheduling/dispatch work, or before changing anything between a cron fire and a published brief.

**Status:** complete. Branch `verifier-law5-gate`. Spec: `docs/superpowers/specs/2026-06-09-p2b-durable-unattended-operation-design.md`. Plan: `docs/superpowers/plans/2026-06-09-p2b-durable-unattended-operation.md`. Scope **A + B + C + D**; dead-man's switch (E) deferred (§8.1).

**What it delivers:** a `scheduling/dispatch.py` layer *above* `run_once` that makes the morning pipeline survive an unattended, repeated, calendar-aware schedule. `run_pipeline`/`run_once` now **return** a `RunOutcome` instead of sending; `dispatch_job` is the **single** writer of the durable run-ledger row and the **single** sender of every owner-facing status. A `(job_id, trading_date)` ledger gives idempotency (double-publish guard) and boot-time backward reconciliation; transient infra failures retry within a bounded budget, then escalate loudly to `failed_infra`; the unattended push channel is session-less WeCom-webhook, with hermes/WeChat as the warm two-way fallback.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `migrations/0004_run_ledger.sql` | `run_ledger` table, unique `(job_id, trading_date)` | 9efa487 |
| 2 | `scheduling/outcome.py` | `RunOutcome(status, detail)` + seven status constants | 210b81e |
| 3 | `storage/repo.py` | `record_run` (on-conflict idempotent) / `get_run_status` | 1164bd9 |
| 4 | `orchestration/runner.py` | `run_pipeline` returns `RunOutcome`; check-before-send guards a duplicate publish | d28167c, cc70758 |
| 5 | `scheduling/run_once.py` | `run_once` returns `RunOutcome`; status-sending moves up to the dispatch layer | 0e1627f, b170b9f |
| 6 | `scheduling/dispatch.py` | `resolve_job` + `JobPlan` — each job its own anchor + tolerance (item A) | 49c8011, df499a8 |
| 7 | `scheduling/dispatch.py` | `dispatch_job` single-sender; ledger no-op guard; boot stale→missed relabel | b2a5ead, 5143dab |
| 8 | `scheduling/dispatch.py` | transient-retry + `failed_infra` escalation; unknown errors fail closed | 325a1b6, 220823d |
| 9 | `scheduling/dispatch.py` | `catch_up` boot reconciliation — a `missed` row per absent day over the last 5 dates | 932d0dc, 80c7f98 |
| 10 | `gateway/im/factory.py` | flip: `wecom_webhook` → WeCom primary + hermes fallback (item D) | bca400e |
| 11 | `scheduling/scheduler.py`, `scheduling/__main__.py` | per-job `job_id` in `add_job`; `run_scheduler()` boot path: timing-safe → catch_up → per-fire cron dispatch | 2183c6b, 64c8de5 |

## Key invariants proved here

- **Double-publish guard.** The unique `(job_id, trading_date)` constraint plus `record_run`'s on-conflict means a second `published` for one job/day is rejected at the DB — a cron-vs-catch-up race cannot publish twice.
- **Single sender, single writer.** All owner-facing status (heartbeat, skip, sub-floor, verify-fail, missed, failed_infra) flows through one place — `dispatch_job._status_text` + `send_with_fallback`; `published` is silent. `run_once`/`run_pipeline` no longer send. One ledger row is written per dispatch.
- **Durable record-then-send seam.** `record_run` writes the row **before** any page is sent (and dispatch checks-before-send), so a row survives a failed page; a crash before the row re-runs and delivers rather than recording a phantom publish.
- **Per-job anchors (item A).** `resolve_job` gives `main` a 07:00 Asia/Shanghai anchor and `premarket` an 18:00 America/New_York anchor with its own tolerance — `main` never inherits premarket timing.
- **Backward reconciliation (finding #2).** `catch_up` writes a `missed` row **per absent day** across the last 5 trading dates (not one misleading row); today is delegated to `dispatch_job(trigger="boot")`, which relabels a stale window to `missed`.
- **Fail-closed transient boundary (finding #7).** Only a curated `_TRANSIENT` tuple retries (bounded by `backoff_ceiling_s` × `max_transient_retries`); any unrecognized error escalates to `failed_infra` immediately with no silent retry. `assert_timing_safe` is left **unchanged** and bounds the single retry budget at boot — the send failover inside `send_with_fallback` is loop-free, so one budget is sufficient (deliberate, flagged in `dispatch.py`).
- **No stale boot-day data.** `run_scheduler`'s `_dispatch` recomputes `now`/`prev` on every cron fire; only the boot `catch_up` call uses boot-time `now`/`prev` (correct for reconciliation). A multi-day daemon never serves yesterday's session data (CLAUDE.md §7).

## How to test

```bash
.venv/Scripts/python.exe -m pytest tests/scheduling tests/orchestration tests/im -v   # all offline
```
Migration `0004_run_ledger.sql` auto-applies via `marketwind.storage.migrate`. The live boot wiring (`scheduling/__main__.py::run_scheduler`, `main`) and live channels are `# pragma: no cover` — exercised only by the manual scheduled-path entrypoint.

## Out of scope — deferred gaps (recorded, not silently dropped)

From spec §8:
1. **Dead-man's switch (item E)** — an out-of-process, pull-based watcher that pages when the node itself is dead or the push channel is down. The only thing that closes the two residual windows below; highest-value next item.
2. **Clawbot session-warmth warning** — warn over WeCom if the hermes/WeChat session wasn't warmed in 24h.
3. **Calendar-skip content posting** — replace the bare non-trading-day heartbeat with a "markets closed, week ahead" note.
4. **Per-attempt retry forensics** — currently only `failed_infra` + `detail`; no per-attempt log.

**Residual silent-miss window (spec §1 / §6).** B + boot-catch-up converts "down across a fire window, then recovered" into a loud, owner-visible signal. It does **nothing** for "down and staying down" (a node that never reboots never runs catch-up) or "the push channel itself is down" (no push can escape a dead channel — only the ledger row + non-zero exit + logs remain). The silent-miss class is **narrowed, not eliminated**; closing the residual is exactly the deferred dead-man's switch's job. A reader must not believe the silent-miss class is fully closed.
