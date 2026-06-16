# Go-Live Smoke Runbook — Deployment & Live Smoke

> **Read when:** executing the first real autonomous push (Tier-0 blockers G0.2/G0.3/G0.4). This is owner-run, live, on the local laptop + Docker Desktop. It is the dress rehearsal for the cloud cutover (deferred).

**Spec:** `docs/superpowers/specs/2026-06-13-deployment-live-smoke-design.md`.
**Channel order:** ADR-0002 — WeChat (hermes) primary, WeCom backup.
**Floor:** `evaluate_floor` `8/1/2` (grounded≥8, primary≥1, outlets≥2), code-flagged "revisit after first smoke run".

## Operating principle

**Each stage's pass gates the next. Each fail has an explicit STOP/diagnose action. Never loosen a gate silently** — re-tuning the floor `8/1/2` or flipping the DEV label are explicit owner decisions, recorded. Accepted costs of this runbook: it burns **real DeepSeek tokens** (Stage 2/3) and does a **real WeChat push** to the owner.

**Pre-req:** the dockerized Postgres is up (`docker compose up -d postgres`) and migrations applied; `.env` carries the DeepSeek key, Bocha key, `DATABASE_URL`, and the host hermes is logged in (WeChat QR done, kept warm by the daily clawbot keepalive). Run python as `.venv/Scripts/python.exe` with `PYTHONPATH=.`.

---

## Stage 1 — Prove the grounded floor clears (G0.3)

Probe the real Scout→enrich path against the most recent real trading day and read the floor numbers. **Burns zero DeepSeek tokens; stops before drafting.**

```
PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --floor-only
```

Expected output (one line) + exit code:

```
grounded=<g> primary=<p> outlets=<o> passed=<bool>
```

- **PASS:** `passed=True` (exit 0) → proceed to Stage 2.
- **FAIL:** `passed=False` (exit non-zero) → **STOP. Do not deploy.** Read which sub-criterion fell short and map to the responsible gap:
  - `primary=0` → primary-tracing recall (`docs/GAPS.md` G1.1 DeepSeek fallback classifier / G1.2 venues beyond cninfo / G1.4 multi-candidate trace).
  - `outlets<2` → crawler reach (gather/Bocha coverage).
  - `grounded<8` → gather thinness (too few quotes pulled).
  - Fix the recall gap, **or** make an explicit owner re-tune of `8/1/2` in `marketwind/scout/runner.py` (record the decision; never a silent loosening). Re-run Stage 1 until `passed=True`.

---

## Stage 2 — One real end-to-end push + DEV-label decision (G0.4)

### ✅ Precondition RESOLVED (fixed in commit `f6f6b64`)

The former blocker — `main()` calling `run_once(...)` without the required `already_published=` argument — **is fixed**. `main()` now builds an `_already()` closure (mirrors `dispatch_job`'s, querying `get_run_status(... == PUBLISHED)`, preserving the double-publish guard) and passes it into `run_once`. The Stage-2 command below runs as written; **no precondition fix is needed.**

### Run

With the DEV label still **ON** (`REPORT_DEV_LABEL` unset/`true`), run the one-shot against the same real day:

```
PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --send-real
```

This runs draft → **hardcoded verifier gate (Law 5)** → commit → real WeChat push (hermes primary, ADR-0002). The report carries the `【DEV / UNVERIFIED — 非正式报告】` prefix.

### Owner eyeballs the report in WeChat — the acceptance signal

- **Trustworthy** → set the flag and confirm the clean label lands:
  ```
  # PowerShell: $env:REPORT_DEV_LABEL="false"
  PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --send-real
  ```
  Confirm the re-run pushes a report **without** the DEV prefix. (Idempotency note: a second `published` for the same job/day is rejected at the ledger — see Stage 2 precondition; for a clean re-test you may need a fresh trading day or to clear the ledger row.)
- **Not yet trustworthy** → keep DEV ON, record the deficiency **loudly** (don't quietly proceed).
- **`verify_fail`** (drafted but the verifier rejected it) → surface it, fix the underlying claim/verifier issue **before** any label flip. No publish happened (fail-closed).

---

## Stage 3 — Persistent daemon dress rehearsal (B, locally)

Bring up the autonomous daemon as a container and prove it self-fires and survives restart.

**Hermes-access decision (finalize here):** the `scheduler` compose service defaults to **in-container** send — it needs the `hermes` CLI on the image PATH and the host hermes creds mounted read-only (`HERMES_HOST_DIR=C:\Users\<you>\.hermes` in `.env`). **If hermes won't containerize cleanly on Windows Docker Desktop, use the host-process fallback** (documented in `docker-compose.yml`): run the daemon on the host against the dockerized Postgres:
```
# host-process fallback (point DATABASE_URL at the published port localhost:5432):
PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --scheduler
```

### In-container path

```
docker compose up -d scheduler
docker compose logs -f scheduler
```

1. **Boot:** confirm `catch_up` runs in the logs and the daemon holds (no crash; awaiting the scheduler's `Event().wait()`).
2. **Self-fire:** temporarily set one cron ~2 min ahead (config override) → watch it fire end-to-end **in-container** → a push lands in WeChat → a ledger row is written (`run_ledger` row for that `(job_id, trading_date)`).
3. **Restart durability:**
   ```
   docker restart <scheduler-container>
   ```
   → it comes back → `catch_up` reconciles → **no duplicate publish** for an already-published day (the unique `(job_id, trading_date)` constraint + record-then-send guard hold).

- **PASS:** self-fired push observed ∧ restart recovers ∧ no double-send.

### G1.5 cold-fail caveat (must fail loud)

WeCom is not yet configured, so the hermes/WeChat fallback is `StubSink`. If the owner's daily clawbot keepalive ever lapses, that morning's cold push can fail `ret=-2` (mislabeled stale-session). This is an **accepted, temporary exposure** (ADR-0002 / `docs/GAPS.md` G1.5): it **must fail loud** (a status/page the owner notices), never a silent skip. Not handled this round.

---

## Stage-2 precondition fix — DONE (commit `f6f6b64`)

This section is retained for history. The `already_published` closure described here was applied to `marketwind/scheduling/__main__.py::main` in commit `f6f6b64` — it queries `get_run_status(... ) == PUBLISHED`, preserving the double-publish guard for the manual path. The Stage-2 command needs no further preparation.

---

## Deferred (out of scope here)

- **Cloud cutover (Stage 4):** provision a China-reachable node, copy the compose stack, set env, `docker compose up`. Mechanical follow-up, written after the node is purchased.
- **WeCom backup setup** (turns G1.5's fallback real).
- **Cold-fail auto-handling (G1.5):** refresh-session-then-retry / §8.2 warmer.
- **Dead-man's switch (G1.3):** the out-of-process watcher closing the residual silent-miss window.
