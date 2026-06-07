# P1c — IM Push + Orchestrator Glue

> **Read when:** picking up IM-push / orchestration work, or before starting the dual-cron triggering layer (P2/P3) that drives `run_pipeline`.

**Status:** complete, including the live WeChat smoke (Task 10, 2026-06-07). Branch `master`. Plan: `docs/superpowers/plans/2026-06-05-p1c-im-push.md`. Task 5 pivoted from a thin httpx iLink client to a `hermes` CLI wrapper — see ADR-0001 (`docs/adr/0001-hermes-weixin-cli-send.md`) and DECISIONS.md D-17a.

**What P1c delivers:** a pluggable IM-push layer and the orchestrator glue that closes the P1 vertical. Channels implement a one-method `IMChannel` protocol (`send(text) -> SendResult`): `HermesWeixin` (primary — shells out to the `hermes` CLI, ADR-0001), `WecomWebhook` (fallback, WeCom group-bot), `StubSink` (tests). Every outbound message is hard-prefixed `【DEV / UNVERIFIED — 非正式报告】` and bounded to ≤500 chars. `run_pipeline` **reuses** `scout.runner.evaluate_floor` to gate on the conjunctive grounded floor (8/1/2) **before** assembling a brief; on shortfall it emits a status message carrying the `trace_id` to a dev channel and returns without any Writer/DeepSeek call. All logic is unit-tested offline on `StubSink` + mocked `subprocess`/`httpx` (23 tests); no automated test touches WeChat credentials or performs a live send.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `gateway/im/base.py`, `stub.py` | `IMChannel` Protocol + `SendResult{ok,error}`; `StubSink` captures sends, configurable fail mode | a07f304 |
| 2 | `gateway/im/label.py` | `DEV_PREFIX`, `MAX_TOTAL=500`, `BODY_BUDGET=474`; `apply_label` prepends the DEV/UNVERIFIED prefix, **fail-closed** (raises) over budget — never truncates | 5303145 |
| 3 | `writer/render.py`, `writer/runner.py` | `render_brief(output, max_chars=MAX_CHARS)` + `run_writer(..., max_chars=500)` — reserve the label budget up front (surgical; defaults preserve P1b) | b7d9a86 |
| 4 | `gateway/im/wecom_webhook.py` | `WecomWebhook` fallback: single httpx POST to a configured group-bot URL; HTTP/transport errors → `ok=False` | fa36ed9 |
| 5 | `gateway/im/hermes_weixin.py` | `HermesWeixin` primary: **shells out to `hermes send --to weixin --json -f -`** (body on stdin/UTF-8), parses JSON `success`; `FileNotFoundError`/timeout/non-zero exit → `ok=False`. Pivoted from the original thin httpx POST — see ADR-0001 (`subprocess` mocked in tests) | b67f98e → a1667bf |
| 6 | `orchestration/runner.py` (`send_with_fallback`) | primary → fallback → raise `RuntimeError` with `trace_id` if both fail | ccd90f9 |
| 7 | `orchestration/runner.py` (`run_pipeline`), `config.py`, `.env.example` | reuse `evaluate_floor`; gate-before-assemble (lazy `make_body`); status-on-shortfall with `trace_id`; IM config fields | 0235ca8 |
| 8 | `gateway/im/factory.py` | `build_channels(settings)` → `(primary, fallback)` by `im_channel`; `hermes_weixin` → `HermesWeixin` + WeCom (or stub) fallback; `wecom_webhook` without URL → `ValueError` | ec9dfdc → a1667bf |
| ADR | `docs/adr/0001-hermes-weixin-cli-send.md`, DECISIONS.md D-17a | record the thin-client → CLI-wrapper pivot (scope=permanent, grantor=owner) | — |

## Key invariants proved here

- **Grounded floor reused, not duplicated:** `run_pipeline` imports `scout.runner.evaluate_floor(sources)` — the 8/1/2 conjunctive gate lives in exactly one place. No second floor implementation exists.
- **Gate before assemble (no wasted Writer call):** `make_body` is a lazy `Callable[[], Awaitable[str]]`; on sub-floor it is never awaited, so a shortfall costs zero DeepSeek/DB calls. A test asserts the producer is never invoked below floor.
- **Label prepend-only / fail-closed (no orphan `[n]`):** the ≤500 cap is reserved up front by rendering at `BODY_BUDGET = 500 − len(DEV_PREFIX)`; `apply_label` only prepends and raises if the labeled length would exceed `MAX_TOTAL`. Truncation stays in `render.py` (the orphan-marker-safe owner), so a marker can never be cut loose from its footnote.
- **Failover exercised:** primary-ok → primary used; primary-fail → fallback used; both-fail → raise carrying the `trace_id` for traceability.
- **DEV/UNVERIFIED honesty:** every published body starts with the DEV prefix (asserted in the above-floor pipeline test).
- **No live WeChat in automated tests:** `subprocess.run` is mocked in the `HermesWeixin` tests and `httpx.post` in the `WecomWebhook` tests; the pipeline tests run entirely on `StubSink`. WeChat credentials never enter this process — the `hermes` CLI reads its own from `~/.hermes/.env` only at live-run time.
- **Live smoke confirmed (Task 10):** `scripts/smoke_p1c.py` drove `build_channels(settings)` → `run_pipeline` end-to-end — [A] above-floor real send (CLI `success:true`, no fallback raised), [B] sub-floor status to dev channel with `make_body` never awaited, [C] broken primary → fallback received the message.

## How to test

```bash
.venv/Scripts/python.exe -m pytest tests/im tests/orchestration -v   # 23 tests, no DB, no network
```

Whole repo (P1a + P1b + P1c, no regressions):
`.venv/Scripts/python.exe -m pytest tests/scout tests/writer tests/im tests/orchestration -v`
— P1c adds 23 passing tests; offline scout/writer all pass. The `test_repo*.py` ERRORS are Postgres-integration tests that need a running DB (`docker compose up -d postgres redis` + `marketwind.storage.migrate`); P1c adds no DB code, so they are unchanged by this phase.

Live smoke (owner-only, gitignored, performs a real WeChat send):
`PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/smoke_p1c.py`

## Config / env additions

| Field | Env | Default | Purpose |
|---|---|---|---|
| `im_channel` | `IM_CHANNEL` | `"stub"` | which channel pair `build_channels` constructs (`stub` \| `hermes_weixin` \| `wecom_webhook`) |
| `hermes_bin` | `HERMES_BIN` | `"hermes"` | path/name of the `hermes` executable `HermesWeixin` invokes |
| `weixin_target` | `WEIXIN_TARGET` | `"weixin"` | `hermes send --to` target (the owner's home channel) |
| `wecom_webhook_url` | `WECOM_WEBHOOK_URL` | `None` | WeCom group-bot fallback URL |
| `weixin_account_id` | `WEIXIN_ACCOUNT_ID` | `None` | retained from the thin-client plan; **unused** by the live CLI path (creds live in `~/.hermes/.env`) |
| `weixin_token` | `WEIXIN_TOKEN` | `None` | retained; **unused** by the live CLI path |

## Out of scope / known gaps

- **`hermes` CLI must be installed and configured (ADR-0001):** the live `hermes_weixin` path requires the `hermes` binary on PATH and `~/.hermes/.env` minted via the owner's QR login (`hermes gateway setup` → Weixin → scan QR). If the binary is missing or the session expires, `HermesWeixin.send` returns `ok=False` and `send_with_fallback` drops to WeCom/stub — it never throws on a missing CLI.
- **WeCom-as-backup vs D-16 (Feishu):** D-P1-3 uses WeCom for the P1 dev test. If WeCom becomes the permanent backup it needs an ADR against D-16 (Feishu). Flag to owner; not blocking.
- **Dual-cron triggering, trading-calendar gating, ConciergeBot two-way receive** — all P2/P3. P1c ships the push + gate glue that the triggering layer will drive; it does not self-trigger yet.
