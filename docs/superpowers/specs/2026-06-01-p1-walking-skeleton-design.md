# P1 — Walking Skeleton Design (Scout → Writer → WeChat dev push)

> **Read when:** implementing or reviewing P1. Companion to `README.md` (phase table), `CITATION_CONTRACT.md` §3.2/§3.3, `ARCHITECTURE.md`, `docs/scout_claude_code_prompt.md` (full-grade Scout brief — P1 builds a deliberate subset).

**Status**: Approved (design) · **Date**: 2026-06-01 · **Phase**: P1

---

## 1. Goal & why P1 exists

Prove the end-to-end vertical — *fetch real domestic sources → assemble a short grounded brief → deliver it* — on one narrow slice, so the two riskiest gaps (Gap-1 primary-fetch and Playwright extraction + span discipline) are de-risked early. P1 is a **walking skeleton**, not a thin demo: narrow surface, full depth.

**Success criterion:** on a real prior trading session, the loop produces a ~500-char Chinese brief whose every factual sentence carries `claim_id`s resolving to stored `(source, quote, span)` records, and pushes it to the owner's WeChat hard-labeled `DEV / UNVERIFIED`. Fully reproducible offline via fixtures.

## 2. Scope

**In:**
- Scout on **one dimension — 昨日复盘 (prior-session recap)**: akshare market numbers + Bocha discovery + Playwright full-text fetch + **one** media-number→primary-disclosure trace, with exact span storage.
- Writer: DeepSeek v4-pro assembles the brief as `(sentence, claim_ids, source_ids)` triples (I8), grounded only (D-1).
- IM push via an `IMChannel` abstraction; `HermesWeixin` primary, `WecomWebhook` fallback, `StubSink` for tests.
- Fixtures/dry-run mode (mandatory) + the span-reconstruction (RF-9) contract test.

**Out (deferred to P2+ — do not build now):**
- Full Gate-0 thresholds (≥30 quant / ≥10 primary / ≥5 outlets) and the bounded incremental-search rounds.
- The Verifier and invariants I1–I12 (P2). P1 publishes to a **dev channel only**, so Law 5 is honored by *not* claiming the output is a verified report.
- Breadth: the other four dimensions (隔夜海外 / 权重股 / 板块·产业链 / 资金·政策·前瞻).
- Outlet-group normalization, warm browser pool, full source-tier ranking (P2).
- WeChat **receive**/two-way (long-polling) — that is ConciergeBot (P3). P1 is **send-only**.
- Dual cron / scheduling (P3) — P1 is run on demand.

## 3. Decomposition (three sub-agents, each TDD)

| Sub-phase | Unit | Output |
|---|---|---|
| **P1a** | Scout (single dimension, full depth) | `Source` + `Quote` records in Postgres → a quote pool |
| **P1b** | Writer | list of `(sentence, claim_ids, source_ids)` → rendered ~500-char brief |
| **P1c** | IM push | brief delivered to WeChat, labeled `DEV / UNVERIFIED` |

Built in order; P1b consumes P1a's persisted pool; P1c consumes P1b's brief.

## 4. Module layout (extends the existing P0 skeleton)

```
marketwind/
  scout/                # P1a (new; L2/L3 boundary)
    query.py            # 昨日复盘 query construction + trading-calendar prev-session calc
    market.py           # akshare: index level / 涨跌幅 / 成交额 / top movers
    discover.py         # Bocha web-search client (UTF-8 body; see note)
    fetch.py            # Playwright fetch → clean main-content → raw_content
    extract.py          # publish_ts parse, quote/span extraction, is_quantitative
    primary.py          # one media→primary-disclosure trace (cninfo/exchange)
    fixtures.py         # dry-run: load saved HTML/JSON, no network
  writer/               # P1b (new)
    writer.py           # DeepSeek grounded assembly → (sentence, claim_ids, source_ids)
    render.py           # triples → ~500-char Chinese brief with [n] markers
  gateway/
    im/                 # P1c (new)
      base.py           # IMChannel interface
      hermes_weixin.py  # iLink send (text)
      wecom_webhook.py  # fallback
      stub.py           # StubSink (tests)
  storage/
    models.py           # Source / Quote / Claim / Sentence (P1 subset)
    migrations: 0002_p1_core.sql
```

akshare/Bocha/Playwright clients live under `scout/` for P1; if reused later they can graduate to `mcp_tools/` (L2). Not pre-abstracting now (Karpathy ②).

## 5. Data model (P1 subset of `CITATION_CONTRACT.md` §3)

Persist the contract's `Source` and `Quote` faithfully (they are the P2 foundation), but only the P1-relevant `Claim`/`Sentence` fields:

- **Source** (§3.2): `url, domain, byline, publish_ts (ISO8601+tz), is_primary, raw_content, ingested_at`. **`raw_content` = cleaned main-content text, stored once; spans index into it.** I5 (ts format) and I9 (`ingested_at − publish_ts ≤ 7d`) enforced at ingest.
- **Quote** (§3.3): `source_id, text, span_start, span_end, context_before, context_after, quote_type, is_quantitative, attached_primary_url`. Span discipline: `raw_content[span_start:span_end] == text` exactly; `context_before+text+context_after` reconstructs (RF-9).
- **Claim / Sentence**: minimal — `claim_id`, `statement`, `quote_ids`, and the sentence triple. **No corroboration/freshness/category machinery in P1** (that's the Verifier, P2). DB CHECK constraints from §3.4 are written as migrations but only those that apply to fields P1 populates.

**Contract delta (P1 → P2):** `is_quantitative` and `attached_primary_url` are P1 working fields **not** present in `CITATION_CONTRACT.md` §3.3 (which models `quote_type` ∈ `factual`/`quoted_inference`/`data`). They are logged here as an explicit P1→P2 contract delta to reconcile when the Verifier lands — P1 does not silently diverge from the contract. (`is_quantitative` ≈ `quote_type = data`; `attached_primary_url` is the per-quote Gap-1 link that §3.4's `has_primary`/primary-source machinery formalizes.)

**Ingest idempotency (decide before P1a code):** P1 reruns constantly against the *same* prior session. Persist with **upsert-by-canonical-url** (re-fetching a URL replaces its Source + re-derives its Quotes, rather than inserting duplicates), OR provide a `--clean-reload` dev flag that truncates the run's pool first. Without this the pool fills with dupes by run 2 and the grounded-floor counts inflate. Default: upsert-by-url.

## 6. Component specs

### P1a — Scout
- **Query construction:** compute "上一交易日" against the A-share trading calendar (akshare `tool_trade_date_hist_sina` + cache, per D-22) — never naive "yesterday". Build Bocha queries for the 昨日复盘 dimension with hard date anchors (上一交易日 / 收盘 / 复盘).
- **Market numbers:** akshare for STAR50 index level / 涨跌幅 / 成交额 / top movers. **Prefer akshare over scraping for numbers it can give authoritatively.** **akshare `is_primary` scope:** primary **only** for market/index *aggregates* (index level, 涨跌幅, 成交额, breadth). Company financials (净利, 营收, 减持额, etc.) are **not** primary just because akshare served them — they still require the cninfo/exchange trace (otherwise Gap-1 leaks through the data vendor).
- **Discovery → fetch:** Bocha returns URL+snippet; Playwright fetches **full text** (snippets never enter a Quote). Single reused browser context + **resource blocking** (abort images/fonts/media/analytics at routing layer) + **layered wait**: terminate on **(network-idle OR DOM-stability) with a hard 15s absolute ceiling** as the third terminator (financial tickers may never idle). **Ceiling-hit disposition:** if usable content loaded by 15s → treat as transient (one retry allowed); if no content → permanent (fail fast, do not retry). No warm pool in P1 (we fetch a handful of pages); pool/concurrency tuning is P2.
- **Clean → `raw_content` (span-freeze rule):** clean the page to main-content text **once**, **freeze** that string as `raw_content`, and index **every** span offset into the frozen string. No re-fetch, no re-normalization, no re-clean anywhere downstream — offsets drift the instant the string changes, producing phantom RF-9 failures. The clean step and the canonical archive are the *same artifact*. Use a pure-Python main-content extractor for Chinese article pages.
- **Extraction:** robust Chinese `publish_ts` parsing (`2026年5月28日`, `5月28日 09:30`, `今晨`, `X小时前`) → ISO8601+tz. **Year-boundary rule:** a bare `月日` (no year) resolves to the **most recent occurrence ≤ ingest time**; relative terms (`X小时前`, `今晨`) resolve against `ingested_at` in its tz. This gates I9, so a wrong year silently drops valid sources. Quote extraction with Chinese financial number detection (`涨0.36%`, `成交3.24万亿`, `净利330.12亿元`); keep enough context to disambiguate 口径.
- **Primary-fetch (one trace, Gap-1):** for one media-reported number, trace to its original disclosure (cninfo/巨潮 or exchange filing), attach `attached_primary_url`, set source `is_primary`. Proves the mechanism; full mapping table is P2.
- **Domestic-only (D-28):** publisher-domain filter, not topic filter (keep 财联社 pieces about US markets).
- **Fixtures mode:** all extraction/parse/primary logic runs on saved HTML/JSON with no network, for deterministic unit tests.

### P1b — Writer
- **Input:** the persisted quote pool. **Grounded only (D-1):** assemble exclusively from quotes; no general-knowledge fill.
- **Output:** list of `(sentence, claim_ids, source_ids)` triples — free-form text forbidden (I8). One claim chain per sentence; no cross-claim synthesis (Law 2) — but P1 has **no Verifier to enforce this**, so the Writer prompt embeds the Iron Laws + `citation/rationalization-table.md` inline as the only guardrail, and the output is schema-checked (I8) before rendering.
- **Model:** DeepSeek v4-pro (OpenAI-compatible, `OPENAI_BASE_URL`/`OPENAI_API_KEY`). It is a **reasoning model** — budget `max_tokens` generously and read `choices[].message.content`, not `reasoning_content`.
- **Render:** triples → ~500-char Chinese brief with `[n]` markers mapping to the source list. **Over-length policy (in `render.py`):** if the assembled brief exceeds 500 chars, **drop whole trailing sentences**, never truncate mid-sentence — a mid-sentence cut orphans a `[n]` marker (a dangling citation = an Iron-Law-1 violation in spirit). Drop from the tail until ≤500 chars, and every surviving `[n]` must still resolve.

### P1c — IM push
- **`IMChannel` interface:** `send(markdown: str) -> SendResult`. Implementations: `HermesWeixin`, `WecomWebhook`, `StubSink`. Channel chosen by config (D-17: plugin, not backbone).
- **`HermesWeixin`:** send-only via iLink Bot using `WEIXIN_ACCOUNT_ID` + `WEIXIN_TOKEN` (minted by `hermes gateway setup` QR login — see §9). Brief ≤500 chars, well under the 4000 limit. **Every message hard-prefixed `【DEV / UNVERIFIED — 非正式报告】`.**
- **Implementation choice:** prefer a **thin send client** over importing the whole `hermes-agent` framework into the service (Karpathy ②); `hermes-agent[messaging]` is used once as a dev tool for the QR setup. *Risk:* if the iLink `send` payload/handshake is non-trivial to reproduce, fall back to calling hermes' send as a library. Resolve during P1c (flagged, not assumed).
- **Fallback:** if HermesWeixin fails, `WecomWebhook` (single URL). *Noted per user; see Decision D-P1-3.*

## 7. End-to-end data flow

```
trading-calendar → 上一交易日
  → akshare numbers + Bocha discovery → Playwright fetch → clean → raw_content
  → extract Source+Quote (+ one primary trace) → Postgres → quote pool
  → Writer (DeepSeek, grounded) → (sentence, claim_ids, source_ids) triples
  → schema check (I8) → render ~500-char brief
  → IMChannel.send (DEV/UNVERIFIED label) → WeChat
```

## 8. Error handling & degradation

- **Recency (I9/RF-5):** drop sources older than 7 days at ingest; never pass downstream.
- **Fetch failures:** distinguish transient (timeout/5xx/nav-abort → retry with backoff+jitter) from permanent (404/paywall/offshore-redirect → fail fast). A permanent fetch failure must not be silently padded.
- **Honest shortfall — the grounded floor (provisional: 8 / 1 / 2, revisit after first smoke run):** P1 publishes the brief **only if ALL** of:
  - `grounded_quotes ≥ 8` — factual quotes with a valid `(source, span)`;
  - `primary_traced_quotes ≥ 1` — ≥1 quote carrying `attached_primary_url` (keeps Gap-1 on the critical path every run);
  - `independent_outlets ≥ 2` — distinct domains after reprint collapse (kills the "8 quotes all from Sina" degenerate pool without importing P2's ≥5).

  This is a **conjunctive** floor so a single-outlet or zero-primary pool cannot sneak through. The literal branch (in the orchestrator): `if not (grounded_quotes >= 8 and primary_traced_quotes >= 1 and independent_outlets >= 2): emit_status(trace_id); return`. Rationale: 8 is high enough that "a brief was produced" means real assembly happened, low enough that a normal prior session clears it (the 5/28 pool had ~10 substantive items); not the P2 Gate-0 thresholds (≥30/≥10/≥5). On shortfall, emit a **status message with a `trace_id`** to the dev channel — never a fabricated or padded brief.
- **No silent stale data:** never present a cached prior-day figure as today's (CLAUDE.md §7).
- **Channel failure:** HermesWeixin send fails → fall back to WecomWebhook → if both fail, log with `trace_id` and exit non-zero.

## 9. Prerequisites & config

- **Validated keys (2026-06-01):** DeepSeek (`OPENAI_API_KEY`, model `deepseek-v4-pro`) ✅; Bocha (`BOCHA_API_KEY`) ✅.
- **WeChat token (action required, interactive):** run `hermes gateway setup` → select Weixin → scan QR with phone → paste `WEIXIN_ACCOUNT_ID` + `WEIXIN_TOKEN` into `.env`. This is **step 1 of P1c** and cannot be done with a static key. WeCom webhook fallback needs only a webhook URL.
- **Bocha request bodies must be UTF-8 JSON** (a `curl -d` Chinese-encoding quirk surfaced during validation; the Python client is unaffected).
- **Secrets:** `.env` holds live keys. A root `.gitignore` is **already in place** (ignores `.env`/`.env.*`, allows `.env.example`) so the keys can't be accidentally committed the moment this becomes a git repo — the exposure window was open while keys sat on disk untracked.

## 10. Testing strategy

- **Fixtures unit tests (offline, deterministic):** `publish_ts` parsing across Chinese/relative formats; Chinese financial-number detection; outlet/domain derivation.
- **Span/RF-9 contract test:** for every extracted quote, `raw_content[span_start:span_end] == text` and `context_before+text+context_after` re-locates in `raw_content`.
- **Writer schema test (I8):** output parses to `(sentence, claim_ids, source_ids)`; every `claim_id`/`source_id` resolves; reject free-form text.
- **Over-length render test:** an over-length Writer output renders to ≤500 chars by dropping whole trailing sentences, and **every** surviving `[n]` still resolves (no orphaned markers).
- **Sub-floor test (stops silent skipping):** feed a fixture pool of 5 quotes / 1 outlet; assert a status message with `trace_id` fires and **no brief renders**. If this test passes, the grounded floor cannot be optimized away.
- **IM test:** `StubSink` captures the payload; assert the `DEV/UNVERIFIED` label and ≤500 chars. No live WeChat in automated tests.
- **Fallback-path test (forces the least-exercised code):** a `StubSink` configured to fail the primary send asserts that `WecomWebhook` is then attempted — so the 7am fallback path is exercised before it's needed for real.
- **Live smoke (manual, gated):** one real run against DeepSeek+Bocha+Playwright and a real WeChat send, run by hand (Law-5-spirit verification before claiming P1 done).
- Migrations: `make migrate` applies `0002_p1_core.sql`; idempotent (per P0 runner).

## 11. Decisions captured (this phase)

- **D-P1-1:** P1 publishes to a **dev channel only**, hard-labeled `DEV / UNVERIFIED`. Real publication + Verifier gate are P2. (Honors Law 5.)
- **D-P1-2:** Scout P1 scope = **one dimension (昨日复盘), full depth**, incl. primary-fetch; breadth + Gate-0 thresholds + outlet-group normalization deferred to P2.
- **D-P1-3:** P1 WeChat = **personal WeChat via Hermes iLink (send-only)**; **WeCom group-bot webhook is the fallback**. *Caveat:* D-16's documented backup is Feishu, not WeCom — acceptable for a P1 dev test; if WeCom-as-backup becomes permanent it needs an ADR against D-16.
- **D-P1-4:** **Fixtures-first** behind clean interfaces, then point at live services.

## 12. Open items to resolve during implementation

1. Thin iLink send client vs. calling `hermes-agent` as a library (P1c) — decide once the send payload complexity is known.
2. Exact pure-Python main-content extractor for Chinese pages (evaluate during P1a).

*(Resolved in this revision: grounded floor = 8/1/2 conjunctive, §8; ingest idempotency = upsert-by-url, §5; over-length, span-freeze, akshare-primary scope, publish_ts year-boundary, Playwright 15s ceiling, contract delta — all now specified. `.gitignore` created so live `.env` keys can't be accidentally committed.)*
