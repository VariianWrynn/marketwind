# ADR-0001 — HermesWeixin sends via the `hermes` CLI, not a raw iLink POST

**Status:** ~~accepted~~ **OVERTURNED 2026-08-05**
**Grantor:** project owner
**Date:** 2026-06-05
**Scope:** permanent
**Expiry condition:** revisit if the `hermes` CLI is dropped as a dependency, or if a maintained in-process iLink client (e.g. importing `hermes_agent` directly) becomes preferable for batching/latency.

> **Overturn note (2026-08-05):** The `hermes send` CLI subcommand specified by this ADR **does not exist** (`hermes: error: argument command: invalid choice: 'send'`). `HermesWeixin` has been rewritten to call hermes' `send_weixin_direct` Python API directly — the option-B approach this ADR originally rejected. See `docs/progress/hermes-weixin-api-bark-alert.md` for the full rationale, verification, and implementation details. The expiry condition ("a maintained in-process iLink client becomes preferable") has been met: `send_weixin_direct` is a stable, documented helper in hermes' codebase.

## Triggering situation

P1c Task 5 originally specified `HermesWeixin` as a *thin* httpx client: a single
static-bearer POST to a best-guess iLink endpoint with a `{account_id, content}`
body (fields marked `# CONFIRM`). During the Task-10 owner smoke (QR login via
`hermes gateway setup` → Weixin), inspection of the installed `hermes_agent`
0.15.2 `gateway/platforms/weixin.py` showed the real send is **not** a static
bearer POST. It requires:

- a per-peer `context_token` session (refreshed, not static),
- version-pinned headers (`iLink-App-Id`, `iLink-App-ClientVersion`,
  `AuthorizationType: ilink_bot_token`, a randomized `X-WECHAT-UIN`),
- a structured message body (`item_list`, `message_type=MSG_TYPE_BOT`).

Reproducing this in a thin in-process client is brittle and would silently rot
on every iLink version bump — unacceptable for a financial push where a wrong or
dropped message has real cost.

Three options were weighed:
- **A.** Reproduce the iLink protocol in-process (httpx/aiohttp). Rejected: brittle, version-coupled, duplicates `hermes_agent` internals.
- **B.** Import `hermes_agent` library internals directly. Rejected: couples us to private internals across versions; heavier than the personal-use scope warrants.
- **C.** Shell out to the installed `hermes` CLI — the tool's supported public surface. **Chosen by the owner.**

## Decision

`HermesWeixin.send(text)` invokes the installed `hermes` CLI as a subprocess:

```
hermes send --to <target> --json -f -
```

- The message body is piped on **stdin** (UTF-8), avoiding argv length/encoding limits.
- `--json` makes the CLI emit a machine-readable result; `success: true` → `SendResult(ok=True)`.
- Exit code: `0` ok, `1` delivery error, `2` usage error. Non-zero → `ok=False` carrying stderr.
- `FileNotFoundError` (no `hermes` on PATH) and `TimeoutExpired` (30 s) → `ok=False` with a clear error.
- **No WeChat credentials live in this process.** The CLI reads its own from `~/.hermes/.env`,
  minted by the owner via QR. The factory therefore no longer requires
  `WEIXIN_ACCOUNT_ID` / `WEIXIN_TOKEN`.

This preserves **D-16** (WeChat primary) and **D-17** (the Hermes adapter is a
pluggable component, not the backbone): swapping `hermes_weixin` for
`wecom_webhook` is still a one-line `IM_CHANNEL` change, and a missing/broken CLI
fails closed to the `WecomWebhook` (or `StubSink`) fallback via
`send_with_fallback`.

## Verification

A real send to the owner's home channel succeeded end-to-end during the smoke:

```
printf '【DEV / UNVERIFIED — 非正式报告】MarketWind P1c 连通性测试，请忽略。' \
  | hermes send --to weixin --json -f -
# -> {"success": true, "platform": "weixin", "chat_id": "…@im.wechat",
#     "message_id": "hermes-weixin-…", "context_token_used": false}  (exit 0)
```

## Affected modules

| Module | Change |
|---|---|
| `marketwind/gateway/im/hermes_weixin.py` | rewritten as a `subprocess` wrapper over `hermes send`; no httpx, no `_ENDPOINT`, no in-process credentials |
| `marketwind/gateway/im/factory.py` | `hermes_weixin` branch builds `HermesWeixin(hermes_bin, target)`; falls back to `WecomWebhook` if a webhook URL is set, else `StubSink`; no longer raises on missing `WEIXIN_*` token |
| `marketwind/config.py` | added `hermes_bin="hermes"`, `weixin_target="weixin"`; `weixin_account_id`/`weixin_token` retained but unused by the live path |
| `.env.example` | WeChat block documents the CLI approach (`IM_CHANNEL`/`HERMES_BIN`/`WEIXIN_TARGET`); no `WEIXIN_ACCOUNT_ID`/`WEIXIN_TOKEN` (creds in `~/.hermes/.env`) |
| `tests/im/test_hermes_weixin.py`, `tests/im/test_factory.py` | mock `subprocess.run`; factory tests cover wecom-fallback and missing-url-raises |

## Relationship to DECISIONS.md

Recorded as a referencing row under "Delivery channel" (D-17). This ADR does not
overturn D-16 or D-17; it changes the *mechanism* of the WeChat adapter from a
thin static-bearer POST (which never worked) to a CLI subprocess, consistent with
the plugin model both decisions assume.
