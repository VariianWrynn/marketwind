# MarketWind — master gap register

> **Read when:** planning what to build next, or before claiming the system is "done." This is the single consolidated list of everything deliberately deferred across all phases, **re-ranked by importance toward the real goal: a trustworthy, autonomous daily live report.** Nothing here was dropped silently — every item traces to a source note.

**Ranking principle.** Tier 0 = blocks a first real live push. Tier 1 = correctness / unattended-reliability (financial Iron-Law alignment + "obvious fail welcomed, silent fail unwelcomed"). Tier 2 = report quality / verification depth. Tier 3 = product second half (inbound). Tier 4 = content-shape niceties / by-design deferrals. Within a tier, higher = do first.

**Fail-closed status.** Every recall gap below already **fails closed** (a miss = no-attach / no-publish / labeled skip, never a fabricated or laundered fact). So the open gaps cost *recall and completeness*, not *safety* — important to keep in mind when ranking.

---

## Tier 0 — Go-live blockers (nothing publishes correctly until these are done)

| ID | Gap | Source | Note |
|---|---|---|---|
| G0.1 | **Credentials / config in place.** Have today (2026-06-13): DeepSeek key, hermes `~/.hermes/.env` (owner QR login done — WeChat is the **primary** per ADR-0002), Bocha key, `DATABASE_URL` (local docker). Still missing: `WECOM_WEBHOOK_URL` — now the **backup** (ADR-0002), so its absence no longer blocks a real push, only leaves the fallback as `StubSink` (see G1.5). | `P1c-im-push.md` env table; `primary-tracing.md`; ADR-0002 | The owner-held creds are in place; only the WeCom backup URL is outstanding. |
| G0.2 | **Deploy & run the daemon persistently**: `scheduling/__main__.py::run_scheduler` is wired but `# pragma: no cover - live` — never run as a process. Postgres up, Docker-compose on the node. | `P2b-durable-unattended.md`; README P0/P4 | The autonomous loop has never actually run unattended. |
| G0.3 | **Prove the grounded floor clears on a live real-time pool.** Under the simulated 2026 clock akshare has no matching disclosures, so a full "today's pool clears the floor" can't be demonstrated; only a historical window is proven. | `primary-tracing.md` §"Recorded limitation — simulated clock" | If the floor never clears, every day sub-floor-skips and **the report never publishes.** This is the riskiest unknown of go-live. |
| G0.4 | **DEV/UNVERIFIED label flip decision.** `gateway/im/label.py` still hard-prefixes every brief `【DEV / UNVERIFIED — 非正式报告】` (a deliberate Law-5 / D-P1-1 guard). | `DECISIONS.md` D-P1-1; `label.py` | Now *permissible* to flip (the Verifier gate exists), but it is an explicit owner decision, not yet made. |

## Tier 1 — Correctness & unattended reliability

| ID | Gap | Source | Note |
|---|---|---|---|
| G1.1 | **DeepSeek fallback classifier is stubbed to `None`** in `enrich_primary_live` (rules-only). Wiring the real call + prompt-regression is a follow-up. | `primary-tracing.md` open gaps | Directly affects whether the floor clears day-to-day (borderline Tier 0): rules-only classification = fewer quantitative quotes routed to a primary trace. |
| G1.2 | **Primary venues beyond cninfo** (Shanghai/Shenzhen exchange filings, regulator, company announcements). Today trace = cninfo/巨潮 only. | `ARCHITECTURE.md` Gap 1; `P1a-scout.md`; `P2a` note | Many days' primaries are not on cninfo; missing venues = lower primary recall = floor risk. |
| G1.3 | **Dead-man's switch (item E)** — out-of-process, pull-based watcher that pages when the node itself is dead or the push channel is down. | `p2b…design.md` §8.1; `P2b-durable-unattended.md` | The **only** thing that closes the residual silent-miss windows ("down & staying down", "push channel down"). Directly serves the "silent fail strongly unwelcomed" mandate. Scope minimally (Karpathy ②: not an elaborate watchdog). |
| G1.4 | **Multi-candidate primary trace.** `trace_to_primary` returns one URL (first disclosure in window, category-narrowed); a figure whose disclosure isn't the top hit misses. | `primary-tracing.md` open gaps | Fails closed (safe), but lower recall → floor risk. |
| G1.5 | **Cold-fail handling for the WeChat primary.** Per ADR-0002 WeChat is the unattended primary, kept warm by the owner's daily clawbot keepalive. If the keepalive lapses, that morning's cold push fails `ret=-2` (mislabeled stale-session). With WeCom not yet set up the fallback is `StubSink` → no real second channel that day. **Decision (owner, 2026-06-13): for now record as a gap, not handled.** Mitigations, in order: (a) set up the WeCom webhook backup (turns the fallback real); (b) refresh-session-then-retry before fallback; (c) if keepalive proves unreliable, build the §8.2 automated warmer. **Must fail loud meanwhile** — a cold-fail must page the owner, never silent-skip. | ADR-0002; `P2a-core-triggering.md` Q5; `CLAUDE.md` §8 | Directly serves "silent fail strongly unwelcomed." Until (a), a keepalive-lapse day has no durable delivery — the loudest-possible failure is the interim guard. |

## Tier 2 — Report quality & verification depth (Verifier Tier-3 + scout recall)

| ID | Gap | Source | Note |
|---|---|---|---|
| G2.1 | **Cross-report storage** (`pipeline_runs` persisting each report's verified-claim set), the data foundation for I11 + the D-14 correction mechanism. | `ARCHITECTURE.md` Gap 3 | Prerequisite for G2.2's I11. |
| G2.2 | **Verifier Tier-3 invariants**: I6 (90-day freshness search, needs network), I11 (cross-report consistency, needs G2.1), I12 (derived_metric methodology — Writer emits no `category`/`methodology`), I3b/I2 (corroboration — Writer emits no `corroboration_status`), I10 time-window precision (Writer emits no `time_window`). | `verifier-law5-gate.md` Tier-3 gaps; `DECISIONS.md` D-11..D-14 | Each needs Claim metadata the Writer doesn't yet emit, or network/history. The current 6-check gate is the floor, not the ceiling. |
| G2.3 | **Claim state machine** (drafted→verified/failed→rewritten, retry ≤ 1), failure-rate thresholds (D-4/D-8), re-run loops, 800-char digest. | `verifier-law5-gate.md`; `DECISIONS.md` D-4/D-8/D-9 | `claim_failures` currently persists violations only; the full state machine is Tier-3. |
| G2.4 | **Mojibake H-share / image-only disclosure PDFs** → garbled/empty extract → no-attach. **No OCR by design** (OCR'ing financial digits is a Law-3 risk). | `primary-tracing.md` open gaps | Permanent lower-recall edge; fail-closed. Likely never "fixed" — listed so it's not rediscovered. |
| G2.5 | **Live per-site `publish_ts` parsing** — per-source work deferred past the P1a smoke. | `P1a-scout.md` | Affects I5/I9 freshness metadata fidelity. |

## Tier 3 — Product second half (inbound / two-way)

| ID | Gap | Source | Note |
|---|---|---|---|
| G3.1 | **ConciergeBot two-way** — inbound message routing, follow-up mini-pipeline, subscription changes. | README P3; `ARCHITECTURE.md` L47; `CLAUDE.md` §0/§7 | The entire receive side of the product. Large, independent subsystem — its own spec. |
| G3.2 | **Intent routing**: function-calling + explicit intent schema + **ask-back when unsure**; side-effectful commands (change cron/subscription) **must confirm first**. | `ARCHITECTURE.md` Gap 5; `CLAUDE.md` §7 | A single-intent classifier will hit a wall on mixed multi-intent messages. Part of G3.1. |
| G3.3 | **Keyword-trigger interface** — `interval` (keyword polling) / `event` (Redis Streams) triggers on the unified `Trigger` protocol. Today only `cron` exists (`scheduling/trigger.py` is a cron-only seam). | README P4; `ARCHITECTURE.md` line 28; `CLAUDE.md` §6 | New triggers implement the protocol + register, no change to the main flow. |

## Tier 4 — Content-shape niceties & by-design deferrals

| ID | Gap | Source | Note |
|---|---|---|---|
| G4.1 | **D-19 self-contained 07:00 report** (includes the pre-market content) + visual fold marker on the repeated part. | `DECISIONS.md` D-19, D-P2-1 (deferred) | Content shape, independent of the triggering layer. |
| G4.2 | **D-20 degraded holiday news-digest** ("markets closed, week ahead"). Today a non-trading day emits a labeled skip status only. | `DECISIONS.md` D-20, D-P2-2 (deferred); `p2b…design.md` §8.3 | A labeled skip is honest and cheap; the digest is a separable content feature. |
| G4.3 | **Per-attempt retry forensics** — currently only `failed_infra` + `detail`, no per-attempt log. | `p2b…design.md` §8.4 | Add only if debugging ever needs it. |
| G4.4 | **attributed_sentiment** — kept as a forbidden stub (unattributed market sentiment rejected under Law 4). | `DECISIONS.md` D-15 | An accepted cost, not a bug. Listed for completeness. |

---

## Recently closed (NOT open gaps — recorded so they aren't re-listed)

- **Clawbot session-warmth keeper (P2b §8.2)** → **resolved by `DECISIONS.md` D-P2b-1**: the owner keeps the WeChat clawbot alive daily; the automated warmer is intentionally not built.
- **cninfo disclosure PDF parsing** → resolved (cninfo-pdf-extraction phase): `scout/cninfo_pdf.py` derives + downloads + extracts the disclosure PDF.
- **Primary-tracing wiring / live-floor unblock** → addressed (`primary-tracing.md`): number-verified cninfo primaries attach after gather.
- **Per-job anchor/tolerance dispatch + boot reconciliation + durable channel** → shipped in P2a/P2b.
