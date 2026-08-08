# HermesWeixin API rewrite + Bark failure alert

> **Read when:** the WeChat send fails silently, `HermesWeixin` returns `ok=False` with an import or credential error, or working on the IM delivery / alert path.

**Status:** complete, 2026-08-05. **Overturns ADR-0001** — the `hermes send` CLI subcommand does not exist; `HermesWeixin` now calls hermes' `send_weixin_direct` Python API directly. Also adds BarkAlert as an out-of-band iOS push when primary delivery fails.

**Why:** ADR-0001 specified `hermes send --to weixin --json -f -` as the WeChat delivery mechanism. During a debug session on 2026-08-05, this was proven false — `hermes` has no `send` subcommand (`hermes: error: argument command: invalid choice: 'send'`). The previous debug session had attempted a direct rewrite using `send_weixin_direct` but left the implementation brittle (hardcoded paths, credentials read from `os.getenv` inside `send()`, tests still mocking `subprocess.run`). This session rewrote it cleanly, added comprehensive tests, verified end-to-end with a real WeChat send, and added Bark as a failure alert channel.

## What was done

| Area | Module | What it does |
|---|---|---|
| HermesWeixin rewrite | `gateway/im/hermes_weixin.py` | Clean implementation using `send_weixin_direct` from hermes' weixin adapter. Constructor takes `token`, `account_id`, `chat_id` (injected from config, not read from env inside `send()`). `_ensure_importable()` adds hermes venv to `sys.path` once. `_run()` bridges sync `send()` to async API via `ThreadPoolExecutor` + `asyncio.run()`. Legacy `**_legacy` absorbs old `hermes_bin`/`target` kwargs. |
| Bark alert | `gateway/im/bark_alert.py` | **New.** `BarkAlert` class — fire-and-forget iOS push via Bark (POST JSON to `https://api.day.app/{key}`). Not an IM channel; an out-of-band alert when primary delivery fails. |
| Alert wiring | `orchestration/runner.py`, `scheduling/run_once.py`, `scheduling/dispatch.py`, `scheduling/__main__.py` | `send_with_fallback` gains optional `alert: IMChannel | None` parameter. When `primary.send()` fails and `alert is not None`, fires `alert.send("MarketWind primary failed: {error}")` before trying fallback. Threaded through `run_pipeline` → `run_once` → `dispatch_job` → `catch_up` → both `main()` and `run_scheduler()` entrypoints. |
| Config | `config.py` | Added `weixin_chat_id: str | None` and `bark_url: str = ""` fields. |
| Factory | `gateway/im/factory.py` | `build_channels` passes `token/account_id/chat_id` to `HermesWeixin()`. New `build_alert(settings)` returns `BarkAlert` if `bark_url` is set, else `None`. |
| Docker | `docker-compose.yml` | Added `BARK_URL` to scheduler env. Ports bound to `127.0.0.1`. `WEIXIN_TOKEN`/`ACCOUNT_ID`/`CHAT_ID` passed through. |
| Writer prompt | `writer/prompt.py` | Category whitelist added to prompt — explicit list of 9 allowed values, `qualitative` and empty string banned. |
| Tests — unit | `tests/im/test_hermes_weixin.py` | 8 tests: success, 3 missing-credential variants, module unavailable, error-dict, exception, legacy-kwargs. All mock `_run` and `_ensure_importable`. |
| Tests — live | `tests/im/test_hermes_weixin_live.py` | **New.** 4 integration tests (`@pytest.mark.live`): import check, iLink API reachability, short message send, long formatted message send. Require real credentials; skipped when absent. |
| Tests — bark | `tests/im/test_bark_alert.py` | **New.** 6 tests: success, HTTP error, transport error, URL trailing slash, factory returns None/built. |
| Tests — alert wiring | `tests/orchestration/test_fallback.py` | 3 new tests: alert fires on primary fail, alert skipped on primary success, `alert=None` is safe. |
| Tests — mock fixes | `tests/scheduling/test_dispatch_job.py`, `tests/im/test_factory.py` | Updated mock signatures to accept `alert=None`; added `weixin_chat_id` to mock settings. |

## ADR-0001 overturn

ADR-0001 specified shelling out to `hermes send --to weixin --json -f -`. This subcommand does not exist:

```
$ hermes send --help
hermes: error: argument command: invalid choice: 'send'
  (choose from 'chat', 'model', 'gateway', 'setup', ...)
```

The hermes CLI has no message-sending subcommand. The actual send path is through the Python API: `gateway.platforms.weixin.send_weixin_direct()`. This function handles context-token recovery, aiohttp session lifecycle, adapter construction, and message formatting — all the complexity that ADR-0001 was trying to avoid by shelling out.

**New approach:** import `send_weixin_direct` from hermes' installed venv (`/opt/hermes-agent/.venv/lib/python3.11/site-packages`), call it with credentials from config. The hermes venv is mounted into the scheduler container at `/opt/hermes-agent/.venv:ro` (already in `docker-compose.prod.yml`).

**Trade-offs accepted:**
- Couples to hermes' Python internals (the `send_weixin_direct` function signature). Mitigated: it's a stable, documented helper in hermes' codebase, and the import is isolated to one line.
- Requires `sys.path` manipulation to find hermes' site-packages. Mitigated: `_ensure_importable()` is idempotent and fails loud if the path is missing.
- Sync-to-async bridge (`ThreadPoolExecutor` + `asyncio.run()`). Mitigated: bounded to one worker, 30s timeout, never blocks the event loop.

## Key invariants

- **Credentials injected, not scavenged.** `HermesWeixin` takes `token/account_id/chat_id` at construction time from `config.py` (which reads `.env`). No `os.getenv` calls inside `send()`.
- **Fail-loud, not silent.** Missing credentials → `SendResult(ok=False, error="WEIXIN_TOKEN not configured")`. Missing hermes module → `SendResult(ok=False, error="hermes weixin module not available")`. No silent degradation.
- **Alert is fire-and-forget.** `BarkAlert.send()` catches all exceptions internally and returns `SendResult`. A Bark failure never blocks the pipeline or the fallback.
- **`alert=None` is the safe default.** Every function in the chain defaults to `alert=None`. Without `BARK_URL` configured, the system behaves exactly as before — no alert code path executes.
- **Live tests are gated.** `@pytest.mark.live` tests hit real WeChat/Bark APIs. Default `pytest` run skips them (`-m "not live"`). Run explicitly with `pytest -m live` when credentials are available.
- **Writer category whitelist.** The prompt now explicitly lists all 9 allowed category values and bans `qualitative`/empty. Reduces LLM hallucination of invalid categories.

## Verification

- **352 unit tests pass** (excluding scout tests needing akshare/playwright which can't install on this host's pip).
- **4 live integration tests pass** — real WeChat messages sent and confirmed received by owner.
- **Bark push verified** — real iOS notification received on owner's device.
- **Scheduler container rebuilt and redeployed** with new code, confirmed healthy with all env vars (`WEIXIN_TOKEN`, `WEIXIN_ACCOUNT_ID`, `WEIXIN_CHAT_ID`, `BARK_URL`) present.

## How to test

```bash
# Unit tests (no network, no credentials)
pytest tests/ -m "not live"

# Live integration tests (needs WEIXIN_* and BARK_URL in env)
pytest tests/im/test_hermes_weixin_live.py -m live -v

# Everything
pytest tests/ -m ""
```

## Config / env additions

| Field | Env | Default | Purpose |
|---|---|---|---|
| `weixin_chat_id` | `WEIXIN_CHAT_ID` | `None` | iLink bot target chat (owner's home channel, from `WEIXIN_HOME_CHANNEL` in `.env`) |
| `bark_url` | `BARK_URL` | `""` | Bark push URL (`https://api.day.app/{device_key}`). Empty = alert disabled |

## Out of scope / known gaps

- **WeCom webhook fallback (G1.5)** — still `StubSink`. Not addressed here.
- **`WEIXIN_CHAT_ID` compose mapping** — `docker-compose.yml` maps `WEIXIN_CHAT_ID: ${WEIXIN_HOME_CHANNEL:-}` (reads host's `WEIXIN_HOME_CHANNEL` into container's `WEIXIN_CHAT_ID`). This is correct but confusing; the `.env` variable name and the config field name differ.
- **ADR-0001 document** — the ADR file itself (`docs/adr/0001-hermes-weixin-cli-send.md`) still describes the CLI approach. This progress note records the overturn; the ADR file should be annotated or superseded by a follow-up ADR.
