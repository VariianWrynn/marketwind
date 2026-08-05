# ADR-0005 — corrected iLink session model + a loud fallback slot

> **Read when:** touching `gateway/im/factory.py`, the primary/fallback pair, or anything that
> reasons about WeChat session expiry / the daily keepalive.

**Status:** complete. Branch `claude/dreamy-nash-529cf8`. ADR: `docs/adr/0005-ilink-session-expiry-model-corrected.md`.
Closes the **silent-fail half of `docs/GAPS.md` G1.5**; opens **G1.6**. `tests/im`,
`tests/orchestration`, `tests/scheduling` green (111 passed).

**No separate design spec, and no plan doc.** The design lives entirely in ADR-0005, written
before any code: it carries the triggering situation, the seven evidence points with source
line references, the five options weighed, and the affected-module list. Per `CLAUDE.md` §8.6
that is the "design was locked upstream" case, named here rather than left silent. The work was
one contained change, so a separate plan file would have restated the ADR.

## What this delivers

Two things, one investigative and one behavioural.

**1. The documented session-expiry model was wrong and is now corrected.** The repo told the
owner to hold the iLink session warm with a daily clawbot keepalive. That mitigation targets
the wrong object. Two different things expire:

| | Per-peer `context_token` | QR bot token (`WEIXIN_TOKEN`) |
|---|---|---|
| Role | payload field for reply continuity | **the credential** — `Authorization: Bearer …` |
| Written by | every inbound message | **only** the QR `status == "confirmed"` branch (`weixin.py:1156`) |
| On `errcode=-14` | **self-heals** — cleared, send retried tokenless, iLink accepts (`weixin.py:1611`) | fatal; re-scan required |

A keepalive refreshes only the token that already self-heals. Nothing but `hermes gateway setup`
mints a new bot token, so **there is no preventive owner action** — the standing instruction is
now "on `-14`, re-scan."

Two premises behind the investigation were checked and **falsified**: there is no upstream
"sessions expire every 1–2 hours" statement (the weixin doc publishes no TTL at all), and
upstream issue #14452 (process isolation) is closed `not_planned` / `implemented_on_main` with
all three mitigations present in installed 0.15.2 — `hermes send` opens its own
`aiohttp.ClientSession` from `~/.hermes/.env` and needs no running Gateway, so **ADR-0001's
CLI-subprocess design is cleared**.

**2. The empty fallback slot now fails loud (ADR-0005 option B).** The investigation surfaced a
live silent-fail path that the brief had not anticipated, and this is the fix for it.

## What was done

| Module | What it does |
|---|---|
| `gateway/im/unconfigured.py` (new) | `UnconfiguredSink(setting)` — an `IMChannel` whose `send()` returns `ok=False` with an error naming the unset setting |
| `gateway/im/factory.py` | the empty `hermes_weixin` fallback slot is `UnconfiguredSink("WECOM_WEBHOOK_URL")`, was `StubSink()` |
| `tests/im/test_unconfigured.py` (new) | the sink reports failure and names the missing setting |
| `tests/im/test_factory.py` | `test_hermes_without_wecom_falls_back_to_stub` **pinned the bug**; replaced by a test that the live fallback slot reports failure |
| `DECISIONS.md`, `docs/GAPS.md`, `deploy/report-node/README.md` | keepalive retired; G1.5 half-closed; G1.6 opened; runbook re-written around the two-token model |

`gateway/im/stub.py` is **deliberately unchanged.** `StubSink` returning `ok=True` is correct
for `im_channel="stub"`, its dev/test role. The bug was using it in a *live* slot, so the fix
belongs in the factory, not the sink.

## The silent-fail chain this closes

Verified in source before the fix, each hop:

```
WeChat -14  →  StubSink.send() → ok=True (message discarded)   stub.py:11-15
            →  send_with_fallback returns, no raise            runner.py:36-38
            →  run_pipeline returns PUBLISHED                  runner.py:100
            →  _status_text(PUBLISHED) is None → no message    dispatch.py:89-90
            →  check_in() fires on `inserted` regardless       dispatch.py:219-220
            ⇒  owner receives nothing; dead-man reads healthy
```

After the fix the same failure runs: `ok=False` → `send_with_fallback` raises (`runner.py:39`)
→ `dispatch_job` records `FAILED_INFRA` (`dispatch.py:191-193`) **after** the ledger write at
`:201`, so the failure is durable → `_status_text` renders the loud `⚠ 基础设施失败` line → that
status send re-raises through the same dead channel (`:217`), so **`check_in()` at `:219-220`
never runs** and the FC dead-man pages over Bark.

The un-caught raise at `dispatch.py:217` is left as-is: it is the "obvious fail" the project
mandates, and both the ledger row and the page survive it. Restructuring dispatch's error
handling was out of scope.

## Key invariant

**A channel that discards a message must never report `ok` in a live primary/fallback slot.**
The RED for this was written to fail against a scaffold that reproduced the real bug — the
first `UnconfiguredSink` returned `ok=True`, and the test failed `assert True is False`, so the
assertion is known to discriminate the exact defect.

## Out of scope — rejected on the record

ADR-0005 options **A** (configure `WECOM_WEBHOOK_URL`), **C** (revert to WeCom-primary), **D**
(build the P2b §8.2 warmer) and **E** (preflight liveness probe) were all rejected by the owner.
Consequence, stated plainly: **B buys notification, not delivery.** With A rejected there is one
delivery route, so a dead bot token still means no report that day — the owner now finds out
instead of believing one landed. D's rejection is recorded explicitly because GAPS.md had filed
the warmer under *Recently closed* with a rationale that is now void; without it the warmer
would read as a live idea and be re-planned.

## Owner action outstanding

`hermes gateway setup` — the bot token minted 2026-06-05 died on 2026-08-05. Until the re-scan
there is no working delivery channel at all.

## How to test

```
export DATABASE_URL='postgresql://marketwind:marketwind@localhost:5432/marketwind'
export REDIS_URL='redis://localhost:6379/0'
python -m pytest tests/im tests/orchestration tests/scheduling -q
```
