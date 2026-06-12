# Deployment & Live Smoke — design

> **Read when:** standing up the first real autonomous push; executing the Tier-0 go-live blockers (G0.1–G0.4).

**Status:** approved (owner, 2026-06-13).

**Goal:** Take MarketWind from "wired but never run unattended" to a **persistent self-firing daemon pushing real, verified reports to the owner's WeChat** — validated end-to-end on the local Docker Desktop as a complete dress rehearsal of the ultimate cloud deployment (B). The cloud cutover is a deliberately separate, mechanical follow-up.

**Scope:** Stages 1–3, all **local** (laptop + Docker Desktop, real clock, real akshare/Bocha/DeepSeek/WeChat). The cloud node does not exist yet (purchased when we reach cutover) and is **out of scope** here — see "Deferred."

---

## Context this resolves (from `docs/GAPS.md`)

- **G0.2** — the daemon (`scheduling/__main__.py::run_scheduler`) is fully wired but `if __name__=="__main__"` runs the one-shot `main()`; the persistent loop has never run as a process.
- **G0.3** (riskiest unknown) — under the test-suite's frozen clock the floor's clearance on a live real-time pool was never demonstrated. Production is real-time (real clock, real akshare), so this collapses to "we haven't *measured* it yet."
- **G0.4** — `gateway/im/label.py` hard-prefixes every brief `【DEV / UNVERIFIED — 非正式报告】`. Flipping is now *permissible* (the hardcoded verifier gate in `run_pipeline` exists) but is an explicit owner decision.
- **G0.1** — credentials. In hand (2026-06-13): DeepSeek key, hermes WeChat QR login (primary, ADR-0002), Bocha key, local `DATABASE_URL`. Outstanding: `WECOM_WEBHOOK_URL` (the *backup*, deferred — no longer blocks a real push).
- **Channel order** is fixed by **ADR-0002**: WeChat (hermes) = unattended primary (kept warm by the owner's daily clawbot keepalive); WeCom-webhook = backup, set up later. Cold-fail handling is **G1.5** (recorded, not handled this round; must fail loud).

---

## The floor definition (the Stage-1 pass criterion)

From `marketwind/scout/runner.py::evaluate_floor`, the grounded floor clears iff **all three** hold (provisional `8/1/2`, code-flagged *"revisit after first smoke run"*):

| Criterion | Constant | Meaning |
|---|---|---|
| `grounded_quotes ≥ 8` | `MIN_GROUNDED_QUOTES` | total quotes across all sources |
| `primary_traced_quotes ≥ 1` | `MIN_PRIMARY_QUOTES` | quotes carrying an `attached_primary_url` |
| `independent_outlets ≥ 2` | `MIN_INDEPENDENT_OUTLETS` | distinct domains that actually contributed a quote |

A sub-floor result is a **labeled skip**, never a fabricated report (fail-closed).

---

## Architecture: two products

This effort delivers (1) a small amount of **deployment code** and (2) a **smoke runbook**. They are independent: the code is TDD'd in the normal way; the runbook is executed live by the owner, with the owner's eyeballing as the acceptance signal for report quality.

### Product 1 — Deployment code (three small units)

#### Unit 1: Floor-probe — `--floor-only` mode in `scheduling/__main__.py`

A new entrypoint mode that runs the **real** Scout→enrich path against the most recent real trading day and prints the `FloorResult`, then **stops before `draft()`**.

- Rationale: isolates the riskiest unknown (G0.3) with a clean numeric readout; burns **zero DeepSeek tokens**; on failure it names *which* sub-criterion fell short, pointing directly at the responsible gap (primary-tracing recall vs. crawler reach vs. gather thinness).
- Reuses the existing live seams: `gather_live` + `enrich_primary_live` (exactly as `main()`/`run_scheduler` wire them), then `evaluate_floor`.
- Output: a single human-readable line — `grounded=… primary=… outlets=… passed=…` — plus a non-zero exit code on sub-floor so the result is scriptable and **obvious** (loud).
- No real send, no draft, no commit. DB connection opened/closed in a `try/finally` (matching the existing entrypoints).

#### Unit 2: Scheduler entrypoint + compose service

- **Entrypoint:** add a `--scheduler` branch so `python -m marketwind.scheduling --scheduler` runs `run_scheduler()` (today only the one-shot `main()` is reachable). Argv with `--scheduler` ⇒ `run_scheduler()`; without ⇒ existing `main()` path. Keep the existing one-shot flags working unchanged.
- **Compose service:** add a `scheduler` service to `docker-compose.yml`:
  - same image as `app` (`build: .`),
  - `command: ["python", "-m", "marketwind.scheduling", "--scheduler"]`,
  - `depends_on: postgres (service_healthy)`,
  - `restart: unless-stopped` (durability — the daemon comes back after a crash/restart and `catch_up` reconciles),
  - env: `DATABASE_URL`, `IM_CHANNEL=hermes_weixin`, `HERMES_BIN`, `WEIXIN_TARGET`, DeepSeek + Bocha keys (passed through from the host `.env`).
  - The existing `app` (uvicorn gateway) service is left as-is; the scheduler is a **separate process/service** (clean separation: the gateway is for the future inbound ConciergeBot, the scheduler is the autonomous push).
- **Hermes access from the container:** the hermes CLI + `~/.hermes/.env` live on the host. The container must reach the hermes send path. This is the one genuinely new integration question for containerized WeChat send and is resolved explicitly in the plan (mount `~/.hermes` read-only + ensure the `hermes` binary is on the image/PATH, OR run the scheduler on the host against the dockerized DB). **Default choice: run the scheduler in-container with `~/.hermes` mounted and `hermes` installed in the image**; if hermes proves awkward to containerize, fall back to host-process scheduler against the dockerized Postgres (both are first-class; the plan picks one after a 5-minute spike and records why).

#### Unit 3: Two config-gated flips (reversible, explicit)

- **Channel flip (ADR-0002):** `run_scheduler` selects `im_channel="hermes_weixin"` (was `"wecom_webhook"`). `factory.build_channels` already yields `HermesWeixin` primary + `WecomWebhook`/`StubSink` fallback for that branch — **no factory change**.
- **DEV-label flip (G0.4):** gate the `apply_label` prefix on a settings flag (e.g. `report_label_mode`) **defaulting to the DEV prefix**. Nothing changes silently; the owner flips the flag *after* Stage 2 approval. Reversible and Law-5-honest (the prefix only drops once a human has seen a verifier-passed report).

### Product 2 — Smoke runbook (gated, ordered, fail-loud)

A strict sequence; **each stage's pass gates the next; each fail has an explicit STOP/diagnose action.** Stored as a runbook doc the owner executes.

**Stage 1 — Prove the floor clears (G0.3).**
- Run `--floor-only` against the most recent real trading day.
- **Pass:** `passed=True`.
- **Fail ⇒ STOP, do not deploy.** Diagnose the failing sub-criterion: `primary=0` → primary-tracing recall (G1.1/G1.2/G1.4); `outlets<2` → crawler reach; `grounded<8` → gather thinness. Fix the recall gap **or** make an explicit owner re-tune of `8/1/2` (never a silent loosening) before proceeding.

**Stage 2 — One real end-to-end push + label decision (G0.4).**
- Run the one-shot `main --send-real` against the same real day (DEV label still ON): draft → hardcoded verifier gate → commit → real WeChat push.
- **Owner eyeballs the report in WeChat (the acceptance signal).**
  - *Trustworthy* → set the label flag, re-run, confirm the clean (non-DEV) label lands.
  - *Not yet* → keep DEV, record the deficiency loudly.
  - *`verify_fail`* (drafted but rejected) → surface it, fix before any flip.

**Stage 3 — Persistent daemon dress rehearsal (B, locally).**
- `docker compose up` the `scheduler` service.
- **Boot:** confirm `catch_up` runs and the daemon holds.
- **Self-fire:** point one cron ~2 min ahead (config override) → watch it fire end-to-end *in-container* → push lands → ledger row written.
- **Restart durability:** `docker restart` the container → it comes back → `catch_up` reconciles → **no duplicate publish** for an already-published day (idempotency).
- **Pass:** self-fired push observed ∧ restart recovers ∧ no double-send.

---

## Error handling & invariants preserved

- **Fail-closed, fail-loud.** Sub-floor = labeled skip; verify-fail = no publish + recorded; the floor-probe exits non-zero on sub-floor. No silent skips (MEMORY: "silent fail strongly unwelcomed").
- **Iron Laws untouched.** The verifier gate stays hardcoded in `run_pipeline` (Law 5); the label flip only changes a *prefix*, not the gate. No change to grounding, claim-id, or primary-source rules.
- **Freshness.** `run_scheduler`'s per-fire `_gather(fire_now, fire_prev)` is preserved — a long-running daemon never serves stale boot-day data.
- **Idempotency / single-sender.** The P2b `dispatch_job` ledger (record-then-send, single writer, single status sender) is unchanged; Stage 3's restart test exercises it.
- **ADR-0002 cold-fail (G1.5).** With WeCom unset, a keepalive-lapse cold-fail has `StubSink` as fallback → must surface loudly. Not handled this round (owner decision); recorded.

## Testing

- **Deploy code (TDD):** `want_real_send`-style pure helpers and the new argv branch get unit tests; `--floor-only` gets a unit test over `evaluate_floor` wiring with injected seams (no network). The compose service and live wiring are smoke-only (consistent with P2a/P2b: live Bocha/Playwright/DeepSeek/WeChat is never in the unit suite).
- **Smoke (live, manual):** the Stage 1–3 runbook; acceptance = owner eyeballing + observed self-fire/restart behavior.
- **Regression:** the full offline suite (`pytest`) must stay green; any Writer/Verifier touch (none expected here) would also run `tests/citation_ground_truth/`.

## Deferred (explicitly out of scope)

- **Cloud cutover (Stage 4):** provision a China-reachable node, copy the compose stack, set env, `docker compose up`. A short mechanical follow-up spec, written after the node is purchased.
- **WeCom backup setup** (turns G1.5's fallback real) — when the owner creates the webhook.
- **Cold-fail auto-handling (G1.5)** — refresh-session-then-retry / §8.2 warmer.
- **Dead-man's switch (G1.3)** — the out-of-process watcher; the residual silent-miss closer. Separate item.
- All Tier 1–4 recall/quality gaps in `docs/GAPS.md`.
