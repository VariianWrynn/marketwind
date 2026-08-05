# ADR-0005 — The iLink session-expiry model was wrong: the daily keepalive cannot prevent `errcode=-14`

**Status:** accepted — **option B granted; A, C, D and E rejected** (see §Decision)
**Grantor:** project owner, 2026-08-05
**Date:** 2026-08-05
**Scope:** permanent (supersedes the operational mitigation in ADR-0002, not its channel ordering)
**Expiry condition:** revisit if `hermes_agent` drops the tokenless-retry fallback in
`_send_text_chunk`, or if iLink starts refreshing the bot token from inbound traffic — either
would restore a role for a keepalive.

## Triggering situation

On 2026-08-05 a live send over the production path failed:

```
hermes send --to weixin --json -f -      # marketwind/gateway/im/hermes_weixin.py:30
{"error": "Weixin send failed: iLink sendmessage error: ret=None errcode=-14 errmsg=session timeout"}
```

ADR-0002 made WeChat the unattended primary on the strength of one mitigation: the owner's
**daily clawbot keepalive** holds the iLink session warm. `deploy/report-node/README.md`
turned that into a standing operational instruction. Investigation of the installed
`hermes_agent` 0.15.2 source shows that mitigation cannot work, because it targets the wrong
object.

## Evidence

All line references are the installed `hermes_agent` 0.15.2 (`gateway/platforms/weixin.py`),
read directly rather than inferred.

**1. Two different things expire, and they are not interchangeable.**

| | Per-peer `context_token` | QR bot token (`WEIXIN_TOKEN`) |
|---|---|---|
| Role | payload field for reply continuity | **the credential** — `Authorization: Bearer …` (`_headers`, :210-221) |
| Written by | every inbound message | **only** `save_weixin_account` (:234-254), whose sole caller is the QR `status == "confirmed"` branch (:1156) |
| Refreshed by inbound traffic | yes | **no — no refresh path exists in the package** |
| On `errcode=-14` | **self-heals**: token cleared, send retried **tokenless**, which iLink accepts (:1611-1621) | fatal — re-scan required |

**2. The `-14` we hit was on a *tokenless* send, so the bot token itself is dead.**
`~/.hermes/weixin/accounts/` holds `c349262df569@im.bot.json` but **no `.context-tokens.json`**,
so `ContextTokenStore.restore()` (:281-296) found nothing and `context_token` was `None`.
The retry branch at :1611 requires a truthy `context_token`, so it never fired — consistent
with the log, which shows five attempts and no `retrying without context_token` line:

```
2026-08-05 19:58:17 … attempt=1/5 … errcode=-14 errmsg=session timeout
…
2026-08-05 19:58:27 ERROR … send failed to=o9cq80w5: … errcode=-14 errmsg=session timeout
```

Since a tokenless send authenticates with the bot token alone, iLink rejected the **bot
token**. Upstream agrees: *"Session expired (`errcode=-14`) — Your login session has expired.
Re-run `hermes gateway setup` to scan a new QR code"*
(`website/docs/user-guide/messaging/weixin.md`).

**3. Therefore the daily keepalive is structurally incapable of preventing this.** An inbound
message refreshes only the `context_token` — the one token that already self-heals. Nothing an
owner can send refreshes the bot token; only a QR re-scan mints a new one.

**4. The claimed expiry windows are both unsupported.**
- **"~1–2 hours"** (upstream docs, per the investigation premise): **no such statement exists.**
  Searched the upstream repo for `expire every 1-2 hours`, `connections expire`, `session
  expires`; the only hit, `docs/session-lifecycle.md`, never mentions weixin/iLink. The weixin
  doc publishes no TTL at all.
- **"~24h"** (`deploy/report-node/README.md`, from the P2a Q5 A/B): not a *bot-token* lifetime.
  Observed here: token minted `saved_at 2026-06-05`, still authenticating 2026-06-07 and
  2026-06-08 (its failures that week were rate limits, which require a valid token), then ~58
  idle days, dead 2026-08-05. So the bot-token lifetime is **> 3 days**, upper bound unmeasured —
  days-to-weeks, not hours. *This does not overturn the P2a Q5 `ret=-2` observation, which
  concerned the context-token path; it establishes that `-14` is a distinct failure mode.*

**5. Upstream issue #14452 (process isolation) does not apply to us.** It is **closed
(`not_planned`, verdict `implemented_on_main`)**, and all three cited mitigations are present
in 0.15.2, verified in source: the `_LIVE_ADAPTERS` registry (:115, :2099), the disk-backed
`ContextTokenStore` restored on every call (:2095-2097), and the `-14` tokenless retry
(:1611). `send_weixin_direct` uses `_LIVE_ADAPTERS` only as a same-process fast path and
otherwise opens **its own** `aiohttp.ClientSession` + `WeixinAdapter` from
`WEIXIN_TOKEN`/`WEIXIN_ACCOUNT_ID` (:2128-2147) — both of which are present in `~/.hermes/.env`.
**`hermes send` needs no running Gateway, so ADR-0001's subprocess design is not implicated
and needs no change.**

**6. The failure is currently silent — the more serious finding.** `WECOM_WEBHOOK_URL` is
unset, so `build_channels` returns `StubSink` as the fallback (`factory.py:16-17`), and
`StubSink.send()` returns `ok=True` while discarding the message (`stub.py:11-15`). Chain:
`send_with_fallback` sees `ok` and returns without raising (`runner.py:36-38`) →
`run_pipeline` returns `PUBLISHED` (`runner.py:100`) → `_status_text(PUBLISHED)` is `None`, so
no status message (`dispatch.py:89-90`) → `check_in(healthcheck_url)` fires on `inserted`
regardless of status (`dispatch.py:219-220`), so the dead-man watcher reads healthy. **The
owner receives nothing and nothing pages.** This directly violates the project's
"silent fail strongly unwelcomed" mandate, and it contradicts G1.5's assurance that a
cold-fail "must fail loud" — the code does the opposite today.

**7. The existing preflight would not have caught it.** `deploy/report-node/check_hermes.py`
validates only that `HERMES_BIN` and its sibling interpreter resolve and sit under the mounted
uv tree. It proves the *plumbing*, never the *credential*, so it passes with a dead session.

## Decision

Retiring the keepalive is not itself a choice; it is a correction of fact (points 1–3). What
the owner decided is what replaces it. **Option B is granted; A, C, D and E are rejected.**

| | Option | Verdict | Effect |
|---|---|---|---|
| A | Configure `WECOM_WEBHOOK_URL` so the fallback is a real channel | **rejected** | no second delivery route is added; a `-14` day delivers nothing |
| **B** | **Make the absent fallback fail loud** — a discarding sink must not report `ok` in a live channel role | **GRANTED** | today's silent success becomes a paging failure |
| C | Revert to WeCom-primary (restore D-P2b-1's original ordering) | **rejected** | WeChat stays primary; ADR-0002's ordering and D-16 stand |
| D | Build the P2b §8.2 automated warmer | **rejected** | stays unbuilt — it would refresh the `context_token`, which already self-heals, and cannot touch the bot token |
| E | Probe session liveness in preflight (`ilink/bot/getconfig`) and page early | **rejected** | no early warning; the owner learns at push time |

**Consequence of B-alone, stated plainly.** B buys *notification*, not *delivery*. With A
rejected there is exactly one delivery route, so a dead bot token means **the report does not
reach the owner that day** — B guarantees only that the owner finds out instead of believing a
report landed. That is the deliberate trade: this is a demo/personal-use project (DECISIONS.md
*Positioning*), where a missed day the owner knows about is acceptable and a missed day the
owner does not know about is not.

**How B pages, verified end to end.** `UnconfiguredSink.send()` returns `ok=False`, so
`send_with_fallback` raises (`runner.py:39`) → `dispatch_job` catches it and records
`FAILED_INFRA` (`dispatch.py:191-193`) → the ledger row is written first (`:201`) so the
failure is durable → `_status_text` renders the loud `⚠ 基础设施失败` line (`:101-102`) → the
attempt to *send* that status re-raises through the same dead channel (`:217`), which means
**`check_in(healthcheck_url)` at `:219-220` never runs** and the FC dead-man watcher pages over
Bark after its silence window. The un-caught raise at `:217` is left as-is by design: it is the
"obvious fail" the project mandates, and the ledger row and the page both survive it.

D is rejected **on the record**, not merely left unbuilt: GAPS.md filed the warmer under
*Recently closed* with the now-void rationale "the owner keeps the clawbot alive daily", so
without an explicit rejection it would read as a live idea and be re-planned.

The standing operational instruction is: **on `errcode=-14`, re-scan with `hermes gateway
setup`.** There is no preventive action the owner can take, and with A and E rejected there is
no automated warning either.

**Revisit triggers.** Grant A if a missed day proves costly; grant E if the 07:00 discovery
window proves too late; grant C if `-14` recurs often enough that per-incident re-scans become
intolerable.

## Affected modules

| Module | Change |
|---|---|
| `marketwind/gateway/im/unconfigured.py` | **new (B)** — `UnconfiguredSink`, an IMChannel that reports `ok=False` naming the unset setting |
| `marketwind/gateway/im/factory.py` | **changed (B)** — the empty `hermes_weixin` fallback slot is now `UnconfiguredSink("WECOM_WEBHOOK_URL")`, was `StubSink()` |
| `tests/im/test_unconfigured.py`, `tests/im/test_factory.py` | **new / changed (B)** — the factory test that pinned `isinstance(fallback, StubSink)` pinned the bug; it now pins that the live fallback slot reports failure |
| `deploy/report-node/README.md` | **done** — daily-keepalive instruction replaced by the two-token model + re-scan instruction; the silent-fail warning replaced by B's loud-fail behaviour |
| `docs/GAPS.md` | **done** — G1.5 re-scoped and its silent half closed by B; G1.6 opened for the manual re-scan; G0.1 note corrected |
| `DECISIONS.md` | **done** — D-P2b-1's keepalive clause amended to point here |
| `marketwind/gateway/im/stub.py` | **no change.** `StubSink` stays exactly as-is: reporting `ok=True` is correct for `im_channel="stub"`, its dev/test role. The bug was using it in a *live* slot, so the fix is in the factory, not the sink |
| `docs/adr/0002-wechat-primary-wecom-backup.md` | **unmodified by design.** Its expiry condition ("revisit if the daily keepalive proves unreliable") is met; this ADR is that revisit |
| `deploy/report-node/check_hermes.py` | **no change** — E rejected |
| `marketwind/gateway/im/hermes_weixin.py`, `docs/adr/0001-…` | **no change.** Point 5 clears the CLI-subprocess design |

## Relationship to DECISIONS.md

- **Amends ADR-0002 / D-P2b-1** on the *mitigation* only: the daily clawbot keepalive is
  retired as a delivery safeguard because it cannot affect the token that expires. The
  primary/fallback **ordering** (WeChat primary, WeCom backup) is untouched — C was rejected.
- **Closes the P2b §8.2 warmer** as a live idea: GAPS.md recorded it under *Recently closed* as
  "resolved by D-P2b-1 — the owner keeps the clawbot alive daily." That rationale is void; with
  D rejected the warmer stays unbuilt for the stronger reason that it would refresh a
  self-healing token.
- **Consistent with D-16** (WeChat primary) and **D-17 / D-17a** (channels pluggable; the
  hermes CLI send mechanism is unaffected).
- Does not touch `CITATION_CONTRACT.md`, so no version bump or ground-truth regression is
  triggered (DECISIONS.md ADR step 3).
