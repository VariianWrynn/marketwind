# Deployment & Live Smoke — deploy code + go-live runbook

> **Read when:** standing up the first real autonomous push, or before changing the entrypoint dispatch, the live channel selection, or the DEV-label flag.

**Status:** deploy code complete (offline suite green). Live smoke (Stages 1–3) is **owner-run** — see `docs/runbooks/go-live-smoke.md`. Spec: `docs/superpowers/specs/2026-06-13-deployment-live-smoke-design.md`. Plan: `docs/superpowers/plans/2026-06-13-deployment-live-smoke.md`.

**What it delivers:** the small deploy-code units that take MarketWind from "wired but never run as a process" to a persistent self-firing local daemon pushing real, verified reports to WeChat — plus the gated smoke runbook that validates it end-to-end on Docker Desktop (the dress rehearsal for the cloud cutover).

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `scheduling/__main__.py` | `--floor-only` mode: `floor_line` / `floor_exit_code` pure helpers + live `floor_probe()` (gather→enrich→`evaluate_floor`, print, non-zero exit on sub-floor; **no draft**, zero DeepSeek tokens) | 17b6a65, a573b0a |
| 2 | `scheduling/__main__.py` | `--scheduler` entrypoint (`want_scheduler`) dispatches `run_scheduler()`; **channel flip** `wecom_webhook`→`hermes_weixin` (ADR-0002) | f209255 |
| 3 | `gateway/im/label.py`, `config.py`, `orchestration/runner.py`, `scheduling/run_once.py`, `scheduling/dispatch.py`, `scheduling/__main__.py` | DEV-label flip behind `report_dev_label` (default `True`); `apply_label(body, *, prefix=DEV_PREFIX)`; `label_prefix` threaded through the full publish chain (run_pipeline ← run_once ← dispatch_job ← catch_up; live entrypoints resolve from the flag) | 0e458b0 |
| 4 | `docker-compose.yml`, `.env.example` | restart-durable `scheduler` service (`build .`, `--scheduler`, `depends_on postgres healthy`, `restart: unless-stopped`, env pass-through, ro hermes-creds mount) | c8ad1e9 |
| 5 | `docs/runbooks/go-live-smoke.md`, this note | gated Stage 1–3 runbook + progress note | _this commit_ |

## Key invariants

- **Floor-probe is draft-free and loud.** `--floor-only` runs the real Scout→enrich path and `evaluate_floor` only — it never calls `draft()` (zero tokens) and **exits non-zero on sub-floor**, so a failing floor is scriptable and obvious. It names which of grounded/primary/outlets fell short.
- **Channel = WeChat primary (ADR-0002).** `run_scheduler` selects `im_channel="hermes_weixin"`; the factory's `hermes_weixin` branch already yields HermesWeixin primary + WeCom/Stub fallback — guarded by `tests/im/test_factory.py::test_hermes_primary_wecom_fallback`. No factory change.
- **DEV-label flip is default-ON, reversible, and Law-5-honest.** The `【DEV / UNVERIFIED】` prefix drops **only** when an owner sets `REPORT_DEV_LABEL=false` after eyeballing a verifier-passed report. The flip changes a *prefix*, never the hardcoded verifier gate. Threading defaults to `DEV_PREFIX` everywhere, so every existing caller/test is unchanged (88 offline tests green).
- **Restart durability.** The `scheduler` service is `restart: unless-stopped`; on reboot `catch_up` reconciles and the unique `(job_id, trading_date)` ledger constraint prevents a duplicate publish for an already-published day (exercised by smoke Stage 3's `docker restart`).
- **Freshness preserved.** `run_scheduler`'s per-fire `_gather(fire_now, fire_prev)` is untouched — a long-running daemon never serves stale boot-day data.

## Known blocker (surfaced, not silently dropped)

- **`main()` is missing `already_published` in its `run_once(...)` call** — a latent gap from P2b. As written, `python -m marketwind.scheduling --send-real` (smoke **Stage 2**) raises `TypeError` before any send. Recommended one-liner fix (mirrors `dispatch_job`'s `_already`, preserving the double-publish guard) is documented in `docs/runbooks/go-live-smoke.md` → "Stage-2 precondition fix". Must be applied before Stage 2. Not auto-fixed here: it touches the financial-publish idempotency seam and wants an explicit owner call on semantics.

## Deferred (recorded, not dropped)

- **Cloud cutover (Stage 4)** — provision a China-reachable node, copy the compose stack, set env, `up`. Mechanical follow-up after the node is purchased.
- **WeCom backup setup** — turns G1.5's fallback real.
- **Cold-fail auto-handling (G1.5)** — keepalive-lapse cold push `ret=-2`; must fail loud meanwhile.
- **Dead-man's switch (G1.3)** — the out-of-process watcher; the residual silent-miss closer.
