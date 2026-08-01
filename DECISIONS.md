# DECISIONS

> **Read when:** before changing any approach, model, channel, or threshold — to avoid re-litigating locked decisions.

Locked design decisions. **Changing any of them requires an ADR** (process at the end). Give evidence; do not quietly swap approaches in the implementation.

---

## Positioning (top-level)

**This is a demo/learning + personal-use project, not a production 24×7 system.** The push target is the project owner (initially).

- Cut speculative production weight: complex Watchdog, canary releases, object-storage long-term archival, the embedding-recall phase (a one-way push system has no feedback signal to train it).
- Keep: grounded citation, multi-source corroboration, citation quality, self-correction, cross-day correction. These are both the hiring signal and the personal-use value.
- Anti-pattern warning: an earlier design was "heavier than a demo, more fragile than production" and got stuck in the middle. Do not return to that state.

**Outward positioning**: describe what the system *does* — grounded generation + full source traceability + cross-day consistency. Never claim a "market gap" or "no one has done this".

---

## Citation / content quality (core)

| ID | Decision | Rationale |
|---|---|---|
| D-1 | **Grounded generation**: the Writer assembles only from the Scout-provided quote pool; filling from general knowledge is forbidden | eradicates the "LLM invents when out of material" failure mode |
| D-2 | **Sentence dichotomy + single claim chain**: every factual sentence carries a claim_id; cross-claim synthesis forbidden | each sentence independently verifiable; the choppier prose is an accepted cost |
| D-3 | **B5 = (a) + quoted-inference exception**: model inference forbidden; the only legal inference is the source's own, carrying attribution | the supply-chain section becomes "who is inferring what today", not the system's own analysis |
| D-4 | **Failure-rate thresholds = 10% / 25%**, the "flag-and-publish-anyway" path removed | warning fatigue hits the owner too; below-bar = no delivery value |
| D-5 | **Holiday thresholds tightened 5pp (5%/15%) + policy claims must have a primary** — *refined (not overturned) by [ADR-0003](docs/adr/0003-trusted-outlet-primary-grade-tier.md): "a primary" now means **primary-grade** (tier ≥ TRUSTED)* | holidays are qualitative-claim heavy, so judge dependence is higher |
| D-7 | **A4 independent source = different domain AND different byline** + quant claims need ≥ 1 primary — *refined (not overturned) by [ADR-0003](docs/adr/0003-trusted-outlet-primary-grade-tier.md): the "≥ 1 primary" the quant claim needs is **primary-grade** (tier ≥ TRUSTED), defined in `source_tier.clears_law3`; the `✓官方核实` badge (tier ≥ DESIGNATED) marks the genuinely-corroborated subset* | AND is stricter than OR; blocks "two reporters at the same outlet" pseudo-corroboration |
| D-8 | **Failure-rate denominator = claim-level**: `(failed + dropped) / all drafted` | claims are the atomic unit; the threshold is more stable on them |
| D-9 | **Claim state machine max retry = 1** | prevents infinite rewrite loops |
| D-10 | **Two accepted costs**: the report reads choppier (cost of verifiability); the supply-chain section is thin on some days (honest reflection of the market) | do not later loosen D-2/D-3 |
| D-31 | **Writer cites short pool aliases (`q1…`, `s1…`), not raw DB UUIDs; aliases are mapped back to real UUIDs *after* I8 validation** | does **not** loosen D-1 (still pool-only, still fail-closed) — it removes a pure mechanical failure mode. Evidence: P1b live smoke, claim c-015 emitted quote_id `…478` for the real `…477` (one-char slip in a 36-char UUID), and the fail-closed I8 validator correctly rejected the whole report over a transcription typo. Copying `q14` is far harder to get wrong than a UUID. Do **not** "fix" the serialization back to raw UUIDs |

### Model (v0.4 — supersedes the former judge decision)

| ID | Decision | Rationale |
|---|---|---|
| D-26 | **DeepSeek V4 Pro across all roles, including the judge; tokens unlimited** | resolves the cost gap; a single capable model everywhere. **Supersedes the former "judge must be Sonnet, not a weak model" decision** — the underlying concern (don't use a weak model for the last line of defense) is preserved by using a capable model, and cost is no longer a constraint. Weak/local models may still serve high-tolerance helpers (ranking, normalization), never the judge. |

### v0.3 additions (driven by audit of a real 5/28 quote pool)

| ID | Decision | Triggering evidence |
|---|---|---|
| D-11 | **I6 freshness widened**: from "subject attributes" to "rolling numeric state carrying a present-tense indicator" (shareholding/capacity/orders) | sample 4: 朱一明 shareholding 7.90%→7.00%, old I6 missed it |
| D-12 | **New `derived_metric` category**: derived metrics must carry a methodology label or use only base figures | item 4: 长鑫 "日赚 3.6 亿 vs 3.17 亿" methodology divergence |
| D-13 | **New `time_window` field + I10/RF-7 time-window-aware** | items 1 vs 6: semis "overnight down" vs "Philly SOX +6% Tuesday" — different windows, not a contradiction |
| D-14 | **New I11 cross-report consistency + correction claim** | item 5: the system's prior-day report dated 美光 trillion as 5/27; today's more precise source confirms 5/26 |
| D-15 | **attributed_sentiment kept as a stub, currently forbidden** | item 10: unattributed market sentiment rejected under Law 4, recorded as an accepted cost |

---

## Delivery channel

| ID | Decision | Rationale |
|---|---|---|
| D-16 | **Primary WeChat, backup Feishu** | owner's choice. WeChat personal-account automation is a known grey area subject to risk-control; Feishu as backup is the accepted mitigation if the WeChat session is cut |
| D-17 | The Hermes WeChat adapter is a **plugin**, not the backbone, so losing any one channel is not fatal | channels are pluggable components |
| D-17a | **`HermesWeixin` sends via the installed `hermes` CLI (`hermes send --to weixin --json -f -`), not a raw in-process iLink POST** — see [ADR-0001](docs/adr/0001-hermes-weixin-cli-send.md) | the real iLink send needs a per-peer `context_token` session + version-pinned headers; a thin static-bearer POST never worked. The CLI is the supported public surface and reads creds from `~/.hermes/.env`, so no WeChat secret lives in this process. Consistent with D-17 (still a pluggable adapter, still fails closed to the WeCom/stub fallback) |
| D-P2b-1 | **AMENDED by [ADR-0002](docs/adr/0002-wechat-primary-wecom-backup.md) (2026-06-13): the primary/fallback ordering is REVERSED — WeChat (hermes) is the unattended primary, WeCom-webhook is the backup. Everything else below still holds (the daily clawbot keepalive holds the WeChat session warm; the §8.2 automated warmer stays unbuilt). The reasoning below is preserved as the record of why WeCom was *originally* chosen as primary.** ~~Unattended delivery primary is the session-less WeCom-webhook; personal WeChat (hermes/iLink) is the warm fallback. The personal-WeChat session is kept warm by the OWNER manually keeping the WeChat clawbot alive every day — a deliberate human-in-the-loop keepalive — so the automated session-warmth keeper (P2b spec §8.2) is NOT built.** | Evidence (`docs/progress/P2a-core-triggering.md` Q5, 2026-06-08): a **cold** tokenless proactive personal-WeChat push after ~24h with no inbound reply **fails** with `ret=-2` (mislabeled *stale-session*, not a rate limit — see `CLAUDE.md` §8); the **same send LANDS (`ok=True`)** once an inbound reply re-warms the session — a clean cold→fail / warm→ok A/B. So *unattended* personal-WeChat push is **not durable** across the iLink ~24h session kill on its own. P2b's resolution: WeCom-webhook (session-less) is the unattended primary (`gateway/im/factory.py` `wecom_webhook` branch), personal WeChat is the fallback, and the owner's daily clawbot keepalive holds the WeChat session warm in lieu of an automated warmer. Consistent with D-16/D-17 (channels pluggable, fail-closed). Revisit only if the manual keepalive proves unreliable, at which point build the §8.2 warmer via ADR.~~ |

---

## Time / scheduling

| ID | Decision | Rationale |
|---|---|---|
| D-18 | **Dual cron**: pre-market brief (dynamic anchor = US close + 2h, not a fixed 06:30) + 07:00 main report | US close shifts with DST; a fixed 06:30 gives too short a window under winter time |
| D-19 | The 07:00 main report is **self-contained** (includes the pre-market content) with a visual fold marker on the repeated part | incremental push breaks report archival independence |
| D-20 | On holidays run a degraded "news digest" (no market agents), title clearly marked as a non-trading day | weekends are policy-dense; not publishing misses the most important window |
| D-21 | Internal storage in UTC; render in each source's native timezone | engineering convention + faster reader verification |
| D-22 | A **trading-calendar service** is required (akshare `tool_trade_date_hist_sina` + local cache fallback) | otherwise the holiday cron emits empty reports |
| D-P2-1 | **Dual-cron mechanics ship in P2a (both jobs, real DST anchor via APScheduler ET cron); D-19's 07:00 self-contained content-split + fold marker is DEFERRED** | phased delivery, not a reversal — the triggering layer is the gating dependency; the content shape is independent and lands later. Consistent with D-18/D-19 |
| D-P2-2 | **Calendar gates a non-trading day with a labeled skip status (to dev channel); D-20's degraded news-digest is DEFERRED** | a labeled skip is honest and cheap; the digest is a content feature, separable from the gate. Consistent with D-20/D-22 |

---

## Feedback mechanism

| ID | Decision | Rationale |
|---|---|---|
| D-23 | **Remove the "which one was most off today" prompt** | negativity bias pollutes the feedback data |
| D-24 | Implicit signals from follow-up behavior ("dig deeper on X" = relevance, "is that number right" = doubt) | truly implicit, no forced rating, no pollution |
| D-25 | A weekly **objective-outcome review** ("of the last 7 days' judgments, which did the market confirm") | anchors on objective outcomes, not subjective impressions |

---

## Resolved infrastructure choices

| ID | Decision |
|---|---|
| D-27 | **Market data source: akshare** (free tier to start) |
| D-28 | **No overseas-site crawling.** Domestic deployment only; all domestic-media reporting — including its coverage of overseas markets (overnight US, Philly SOX) — is retained. Drops the overseas-worker / proxy complexity entirely |
| D-29 | **Report archival: dual-write markdown + structured JSON** (human-friendly + machine-friendly for cross-report consistency and future analysis) |
| D-30 | **Project name: MarketWind (市风)** |
| D-32 | **The stack applies DB migrations at boot.** A one-shot `migrate` compose service runs `python -m marketwind.storage.migrate` and `app`/`scheduler` gate on `service_completed_successfully`; the runner now fails loud when it finds no migration files. Overturns the previously-documented "migrations are owner-run" — see [ADR-0004](docs/adr/0004-stack-applies-migrations.md) |

---

## ADR process (to change any decision above)

1. Create `docs/adr/NNNN-<title>.md` with: triggering situation, scope of change (one-off / period / permanent), expiry condition, grantor + date.
2. List the affected downstream modules.
3. If the change touches `CITATION_CONTRACT.md`: bump version + trigger the full `tests/citation_ground_truth/` regression.
4. An exception without an ADR = a violation, recorded in `claim_failures.meta_violations`.
