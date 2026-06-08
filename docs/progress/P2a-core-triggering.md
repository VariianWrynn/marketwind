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
- **Per-job anchor/tolerance dispatch (P2b):** `build_scheduler` registers both jobs against one parameterless `run`, and the smoke `main()` always computes the **premarket** anchor (18:00 ET) with `premarket_tolerance_min`. `main_report_time_cst` / `main_tolerance_min` are therefore currently dead config — the 07:00 CST job must be wired to its OWN anchor + tolerance before it can fire correctly (today only `--force-calendar` premarket smoke is exercised).
- **P2b resilience:** run-ledger + boot-time catch-up, holiday-vs-infra-dead escalation, owner-visible failure pages, transient-retry execution + non-retryable paging, dead-man's switch, durable both-channels-fail.

## How to test
`.venv/Scripts/python.exe -m pytest tests/scheduling -v` — all offline, no DB/network.
Live smoke (owner-only): `PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling.run_once --force-calendar --send-real` (seed a floor-passing pool first, or expect a sub-floor status until primary-tracing lands).
