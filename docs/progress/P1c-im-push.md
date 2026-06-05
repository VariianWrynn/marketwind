# P1c — IM Push + Orchestrator Glue

> **Read when:** picking up IM-push / orchestration work, or before starting the dual-cron triggering layer (P2/P3) that drives `run_pipeline`.

**Status:** complete (automated scope). Branch `master`. Plan: `docs/superpowers/plans/2026-06-05-p1c-im-push.md`. Live WeChat smoke (Task 10) is owner-performed and pending a QR-minted token.

**What P1c delivers:** a pluggable IM-push layer and the orchestrator glue that closes the P1 vertical. Channels implement a one-method `IMChannel` protocol (`send(text) -> SendResult`): `HermesWeixin` (primary, thin iLink httpx POST), `WecomWebhook` (fallback, WeCom group-bot), `StubSink` (tests). Every outbound message is hard-prefixed `【DEV / UNVERIFIED — 非正式报告】` and bounded to ≤500 chars. `run_pipeline` **reuses** `scout.runner.evaluate_floor` to gate on the conjunctive grounded floor (8/1/2) **before** assembling a brief; on shortfall it emits a status message carrying the `trace_id` to a dev channel and returns without any Writer/DeepSeek call. All logic is unit-tested offline on `StubSink` + fixtures (21 tests); no automated test touches WeChat credentials or performs a live send.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `gateway/im/base.py`, `stub.py` | `IMChannel` Protocol + `SendResult{ok,error}`; `StubSink` captures sends, configurable fail mode | a07f304 |
| 2 | `gateway/im/label.py` | `DEV_PREFIX`, `MAX_TOTAL=500`, `BODY_BUDGET=474`; `apply_label` prepends the DEV/UNVERIFIED prefix, **fail-closed** (raises) over budget — never truncates | 5303145 |
| 3 | `writer/render.py`, `writer/runner.py` | `render_brief(output, max_chars=MAX_CHARS)` + `run_writer(..., max_chars=500)` — reserve the label budget up front (surgical; defaults preserve P1b) | b7d9a86 |
| 4 | `gateway/im/wecom_webhook.py` | `WecomWebhook` fallback: single httpx POST to a configured group-bot URL; HTTP/transport errors → `ok=False` | fa36ed9 |
| 5 | `gateway/im/hermes_weixin.py` | `HermesWeixin` primary: thin httpx iLink POST, static bearer token; endpoint/field names marked `# CONFIRM` (mocked in tests) | b67f98e |
| 6 | `orchestration/runner.py` (`send_with_fallback`) | primary → fallback → raise `RuntimeError` with `trace_id` if both fail | ccd90f9 |
| 7 | `orchestration/runner.py` (`run_pipeline`), `config.py`, `.env.example` | reuse `evaluate_floor`; gate-before-assemble (lazy `make_body`); status-on-shortfall with `trace_id`; IM config fields | 0235ca8 |
| 8 | `gateway/im/factory.py` | `build_channels(settings)` → `(primary, fallback)` by `im_channel`; missing token → `ValueError` | ec9dfdc |

## Key invariants proved here

- **Grounded floor reused, not duplicated:** `run_pipeline` imports `scout.runner.evaluate_floor(sources)` — the 8/1/2 conjunctive gate lives in exactly one place. No second floor implementation exists.
- **Gate before assemble (no wasted Writer call):** `make_body` is a lazy `Callable[[], Awaitable[str]]`; on sub-floor it is never awaited, so a shortfall costs zero DeepSeek/DB calls. A test asserts the producer is never invoked below floor.
- **Label prepend-only / fail-closed (no orphan `[n]`):** the ≤500 cap is reserved up front by rendering at `BODY_BUDGET = 500 − len(DEV_PREFIX)`; `apply_label` only prepends and raises if the labeled length would exceed `MAX_TOTAL`. Truncation stays in `render.py` (the orphan-marker-safe owner), so a marker can never be cut loose from its footnote.
- **Failover exercised:** primary-ok → primary used; primary-fail → fallback used; both-fail → raise carrying the `trace_id` for traceability.
- **DEV/UNVERIFIED honesty:** every published body starts with the DEV prefix (asserted in the above-floor pipeline test).
- **No live WeChat in automated tests:** `httpx.post` is mocked in channel tests; the pipeline tests run entirely on `StubSink`. Credentials are owner-minted and only read by the factory at live-run time.

## How to test

```bash
.venv/Scripts/python.exe -m pytest tests/im tests/orchestration -v   # 21 tests, no DB, no network
```

Whole repo (P1a + P1b + P1c, no regressions):
`.venv/Scripts/python.exe -m pytest tests/scout tests/writer tests/im tests/orchestration -v`
— P1c adds 21 passing tests; offline scout/writer all pass. The 6 `test_repo*.py` ERRORS are Postgres-integration tests that need a running DB (`docker compose up -d postgres redis` + `marketwind.storage.migrate`); P1c adds no DB code, so they are unchanged by this phase.

## Config / env additions

| Field | Env | Default | Purpose |
|---|---|---|---|
| `im_channel` | `IM_CHANNEL` | `"stub"` | which channel pair `build_channels` constructs |
| `weixin_account_id` | `WEIXIN_ACCOUNT_ID` | `None` | iLink account id (owner-minted via QR) |
| `weixin_token` | `WEIXIN_TOKEN` | `None` | iLink bearer token (owner-minted via QR) |
| `wecom_webhook_url` | `WECOM_WEBHOOK_URL` | `None` | WeCom group-bot fallback URL |

## Out of scope / known gaps

- **Live iLink field confirmation (Task 5):** `HermesWeixin._ENDPOINT` and the POST body field names (`account_id`/`content`, header vs body token) are best-guess placeholders marked `# CONFIRM`. Unit tests mock `httpx.post`, so they pass regardless; the real shape must be confirmed against a live token during the owner smoke. If the send turns out to need session refresh / multi-step auth, fall back to the `hermes-agent` library and record an ADR against D-17.
- **WeCom-as-backup vs D-16 (Feishu):** D-P1-3 uses WeCom for the P1 dev test. If WeCom becomes the permanent backup it needs an ADR against D-16 (Feishu). Flag to owner after the live smoke; not blocking.
- **Live smoke (Task 10):** owner runs `hermes gateway setup` → Weixin → QR scan, pastes credentials into `.env`, then runs a gitignored `scripts/smoke_p1c.py` to confirm a labeled brief arrives and the fallback fires. The harness pauses here.
- **Dual-cron triggering, trading-calendar gating, ConciergeBot two-way receive** — all P2/P3. P1c ships the push + gate glue that the triggering layer will drive; it does not self-trigger yet.
