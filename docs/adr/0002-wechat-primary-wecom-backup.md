# ADR-0002 — WeChat (hermes) is the unattended primary; WeCom-webhook is the backup

**Status:** accepted
**Grantor:** project owner
**Date:** 2026-06-13
**Scope:** permanent
**Expiry condition:** revisit if the owner's daily clawbot keepalive proves unreliable in practice (cold `ret=-2` failures start reaching the owner), at which point either build the automated session-warmth keeper (P2b spec §8.2) or revert to WeCom-primary — both via a new ADR.

## Triggering situation

During P2a/P2b, **D-P2b-1** set the *session-less WeCom-webhook* as the unattended
delivery primary, with personal WeChat (hermes/iLink) as the warm fallback. That
choice was driven by the P2a Q5 evidence: a **cold** WeChat push after ~24h with
no inbound reply **fails** with `ret=-2` (a mislabeled stale-session signal, not a
rate limit), while the **same send lands once an inbound reply re-warms the
session** — a clean cold→fail / warm→ok A/B.

On 2026-06-13, while scoping deployment + live smoke, the owner clarified that
**WeChat must be the primary channel**, consistent with the original **D-16**
(WeChat primary, Feishu/WeCom backup). The reconciliation with the Q5 evidence is
the keepalive condition we also agreed in **D-P2b-1**: the owner **keeps the
WeChat clawbot alive every day**, which holds the iLink session warm. A warm
session does not hit `ret=-2`, so WeChat-primary is sound *so long as the daily
keepalive holds*. WeCom is not yet set up and is demoted to backup.

## Decision

- **WeChat (hermes) = unattended primary**, kept warm by the owner's daily
  clawbot keepalive (the deliberate human-in-the-loop warmer; the automated
  §8.2 warmer remains NOT built, per D-P2b-1).
- **WeCom-webhook = backup**, configured later when the owner sets up the webhook URL.
- **Code:** `scheduling/__main__.py::run_scheduler` selects `im_channel="hermes_weixin"`
  (was `"wecom_webhook"`). `gateway/im/factory.py` already builds the correct
  pair for that branch: `HermesWeixin` primary + `WecomWebhook` fallback (or
  `StubSink` when no webhook URL is set). No factory change is needed.

## Residual risk (accepted)

If the daily keepalive ever lapses, that morning's push can **cold-fail** with
`ret=-2`. With WeCom not yet configured, the fallback is `StubSink`, so on a
keepalive-lapse day there is currently **no real second channel**. This is an
accepted, *temporary* exposure. It must **fail loud** — a status/page the owner
notices — never a silent skip ("silent fail strongly unwelcomed"). The
cold-fail handling work is recorded as gap **G1.5** in `docs/GAPS.md`; the durable
mitigation is to set up the WeCom webhook (turns the fallback real) and, if
keepalive proves unreliable, build the §8.2 warmer.

## Affected modules

| Module | Change |
|---|---|
| `marketwind/scheduling/__main__.py` | `run_scheduler` `im_channel` flips `"wecom_webhook"` → `"hermes_weixin"` (carried as a task in the deployment plan) |
| `marketwind/gateway/im/factory.py` | none — the `hermes_weixin` branch already yields hermes-primary + wecom/stub-fallback |
| `DECISIONS.md` | D-P2b-1 annotated **AMENDED by ADR-0002** (primary/fallback ordering reversed) |
| `docs/GAPS.md` | G0.1 updated (WeCom = backup, set up later); new **G1.5** cold-fail handling |

## Relationship to DECISIONS.md

**Amends D-P2b-1**: reverses the primary/fallback ordering (WeChat primary, WeCom
backup) while keeping everything else D-P2b-1 established — the daily clawbot
keepalive, the §8.2 warmer staying unbuilt, fail-closed/loud behavior. Restores
the intent of **D-16** (WeChat primary). Consistent with **D-17** (channels
pluggable) and **ADR-0001** (the hermes CLI send mechanism).
