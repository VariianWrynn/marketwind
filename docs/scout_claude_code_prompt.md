# Claude Code task: implement **Scout**, the retrieval/fetch layer for the STAR50 morning-report pipeline

## Read first (ground yourself in the repo before designing anything)
Before writing a line, read these and treat them as the source of truth; my brief below summarizes them but they govern:
- `CITATION_CONTRACT.md` §3.2 / §3.3 (the `Source` and `Quote` data models)
- `citation/glossary.md` (independence / dedup definitions)
- the design doc that defines the `D-`, `Gap-`, `I-`, `RF-`, `Gate-`, `Law-` IDs referenced here
If anything below conflicts with those files, flag the conflict — do not silently pick one.
Bocha = Discovery, Playwright = Enforced Segment Scraping, Raw Sources via Dual-Channel Pipeline

## Role & objective
You are building **Scout**, the retrieval layer of an automated 科创50 (STAR 50) **pre-market** morning-report pipeline. Scout's job: given a day's information needs, search **domestic Chinese** sources, fetch **full article text**, extract structured `Source` + `Quote` records, **trace every reported number back to its primary disclosure**, and hand a verifiable quote pool to a downstream Writer (gated by Gate 0) and Verifier. Scout never writes prose — it produces evidence.

## Where Scout sits
`Scout (you) → quote pool → Gate 0 (threshold check) → Writer → Verifier (span/hallucination check)`
Downstream agents must never fall back on model memory — grounded generation only (Law 4 / D-1). Scout is what makes that possible: if it doesn't fetch and store it, it doesn't exist.

## Tech stack — already decided, use these, don't reinvent
- **Bocha API (博查)** — primary search/discovery. Returns URL + snippet. China-reachable.
- **Playwright (headless Chromium)** — fallback for full-page fetch when a snippet is insufficient. **Rule: anything entering a `Quote` must come from fetched full text, never a snippet.**
- **akshare** — numeric **market data** (index level/涨跌幅/成交额, company financials). Do NOT scrape news pages for figures akshare can give authoritatively.
- **Deployment:** self-hosted on a server inside mainland China. All extraction must run **fully offline** (no overseas SaaS calls). Prefer pure-Python extraction libraries installable from PyPI/domestic mirrors.

## The data contract (non-negotiable output schema)
Every fetched item yields one `Source` plus zero or more sentence-level `Quote`s.

| Record | Field | Notes |
|---|---|---|
| Source | `url` | as fetched |
| Source | `domain` | derived from url |
| Source | `byline` | nullable; reporter/author |
| Source | `publish_ts` | **ISO 8601 with timezone — never a raw string (I5)** |
| Source | `is_primary` | bool: announcement / financial report / regulatory filing / official channel |
| Source | `raw_content` | **cleaned, normalized full-article text, not raw HTML and not a snippet** (the canonical archive quote spans index into) |
| Source | `ingested_at` | ISO 8601 + tz |
| Quote | `text` | one sentence |
| Quote | `span_start`, `span_end` | char offsets **into `raw_content`**; must re-locate the text exactly |
| Quote | `context_before`, `context_after` | one sentence on each side |
| Quote | `is_quantitative` | bool |
| Quote | `attached_primary_url` | nullable; the primary disclosure backing this number |

**Why spans matter:** the Verifier reconstructs `context_before + text + context_after` and matches it against `raw_content` to catch hallucinated quotes (RF-9). Spans must be exact and stable. **Critical discipline:** clean/normalize the page to main-content text **once**, store that as `raw_content`, and extract every span offset against *that stored string*. Do not store raw HTML as `raw_content` (offsets into `<div>` soup are meaningless and break reconstruction), and never re-fetch or re-clean later (offsets drift). The cleaning step and the canonical archive are the same artifact.

## Hard constraints
- **Domestic-only crawl (D-28).** Only fetch domestic Chinese domains; drop X / foreign-media direct crawl. **But** domestic media *reporting on* overseas markets (overnight US, Philly SOX via 财联社/新浪) is fully in scope. → This is a **publisher-domain** filter, not a content-topic filter. Never drop a 财联社 piece just because it's about US stocks.
- **Recency guard (I9 / RF-5).** If `ingested_at − publish_ts > 7 days` → Red Flag; filter at ingest, do not pass downstream.
- **Primary-fetch (Gap 1, HIGHEST priority).** When a number comes from media reporting, trace it to the original disclosure — 巨潮/cninfo (announcements, prospectuses), exchange filings (上交所/深交所), company official channels, regulators (CSRC/PBoC/MIIT). Media restatement alone → `is_primary = 0`, which jams the pipeline at Gate 0. Primary-source extraction is also what collapses reprints into a single source.

## Independence / dedup signals Scout must preserve
- **Independent source = different `domain` AND different `byline`** (AND, not OR).
- Same article reprinted across domains = **one** source. Same reporter across platforms = **one** source.
- Capture `byline`; detect reprint / wire-origin (a 新华社 wire carried by three outlets = one source).
- **Outlet-group trap to solve:** many distinct domains belong to one media group — `finance.sina.com.cn`, `k.sina.com.cn`, `m.sina...` = 新浪系; `cls.cn` & `m.cls.cn` = 财联社. The `domain` field alone under-counts this and lets aggregator sprawl fake corroboration. Decide how you normalize outlet identity so the ≥5-independent-outlets gate can't be gamed by one group.

## Gate 0 thresholds Scout's output must enable
- ≥ **30** quantitative-eligible quotes
- ≥ **10** primary-source-attached quotes
- ≥ **5** independent outlets (group-normalized, per above)

If short → **incremental search, ≤ 2 rounds**, each targeting the *specific* missing dimension/threshold (not a re-run of the same query); then drop that section rather than pad. Build a bounded retry mechanism keyed to which threshold is short.

## What YOU must design (never specified — propose a design, get my sign-off, THEN implement)
1. **Query construction.** How to turn "today's STAR50 pre-market" into concrete Bocha queries; decompose into the five dimensions (隔夜海外 / 昨日复盘 / 权重股 / 板块·产业链 / 资金·政策·前瞻) and into per-company / per-topic queries. Must embed strong date anchors (今日 / 上一交易日 / 隔夜) to avoid recalling stale articles, and must compute "上一交易日" correctly against the A-share trading calendar (weekends/holidays).
2. **Round strategy.** Define what a "round" is; how an incremental round targets a specific coverage/threshold gap vs. re-running a query; how the ≤2-round budget is spent.
3. **Dedup mechanics.** URL canonicalization? content similarity (simhash / embeddings)? byline + first-publish-time? Specify exactly how reprint/wire detection works and how outlet-group normalization plugs in.
4. **Ranking / selection.** When a query returns many candidates, which become Sources/Quotes — using source tier, recency, primary-ness, and marginal contribution to independence.
5. **Primary-fetch procedure.** Concrete steps to find the originating filing from a media number: query cninfo by company + date? follow the article's own attribution? Map claim-types (IPO过会 / 募资 / 减持 / 业绩 / 政策) to the right primary venue.

## Domain knowledge to encode (China-self-hosted fetcher)
- Treat **structured extraction** (publish_ts, quantitative quotes, outlet identity) as the hard part — **not** page-load speed.
- **publish_ts:** robustly parse Chinese / mobile formats (`2026年5月28日`, `5月28日 09:30`, `今晨`, `X小时前`, relative) → normalize to ISO 8601 + tz; reconcile with page metadata; handle year-boundary inference.
- **Quantitative quotes:** detect Chinese financial number formats — `涨0.36%`, `跌超3%`, `成交3.24万亿`, `募资295亿元`, `净利330.12亿元`, `48个交易日`, `同比增长44.8%`, `减持630万股 / 套现超20亿`. Keep enough surrounding context to disambiguate **口径** (净利润 vs 归母净利润; 科创板 vs 全A股 ranking) — different 口径 of the "same" number are **not** duplicates.
- Prefer **akshare** over news scraping for numeric market data and financials.

### Fetcher performance & robustness — address each of these five in the design doc
Correctness outranks latency for this pipeline, so these are not the headline — but a naive fetcher fails on all five, and the design doc should say how you handle each:
1. **Cold-start cost → warm pool.** Launching Chromium per request costs ~1–3s. Keep a pool of warm browser contexts and reuse them; **recycle each context after N uses** because long-lived browsers leak memory heavily. Specify the pool size and recycle threshold.
2. **Loading everything → network-layer resource blocking.** Images/fonts/video/ads/analytics are often 80%+ of bytes and time. **Block them by aborting requests at the routing layer** (not after load); keep stylesheets only if interaction needs them. This is the biggest single latency win (~3–5×).
3. **Page-ready heuristic → layered wait, not `sleep()`.** A fixed sleep wastes time or fires early. Use a **combined** signal: network-idle **+** a DOM-stability check (innerHTML/size stops mutating for a quiet window) **+** an optional selector wait. Note: financial pages with long-polling tickers/websockets may **never** reach network-idle, so DOM-stability must be the fallback that can fire on its own — don't block solely on network-idle.
4. **Garbage extraction → clean main-content, and it produces `raw_content`.** Never pass raw `page.content()` HTML downstream — it's nav/ads/boilerplate and bloats tokens; the extraction layer is the real bottleneck per current benchmark research. The cleaned main-content text **is** the `raw_content` field defined in the data contract (clean once, store, index spans into it — see "Why spans matter"). Use a pure-Python extractor suited to Chinese article pages.
5. **No discipline → bounded concurrency + disciplined retries.** Unbounded parallelism crashes the box (cap concurrent navigations relative to pool size); add retries with **exponential backoff + jitter**. **Distinguish transient failures (timeout, 5xx, navigation abort) from permanent ones (404, blocked/redirected-offshore, hard paywall)** — retry the former, fail fast on the latter, and make sure a permanent fetch failure does **not** consume one of the ≤2 Gate-0 incremental-search rounds.

- **Browser binary:** bake it into the image or use a domestic mirror (npmmirror) — the upstream CDN may be blocked from China.
- **Source tiers (取舍):**
  - 🟢 exchanges / CSRC / 中证指数公司 / 新华社 / 中国证券报 / 上海证券报 / 证券时报 / 第一财经 / 财联社
  - 🟡 东方财富·同花顺资讯 / 中国基金报 / 券商研报 (note broker) / 观察者网 / 证券之星
  - 🟠 雪球 · 东方财富股吧 · 个人公众号 — label "市场讨论", sentiment only
  - 🔴 荐股软文 / 标题党 / 无署名小道消息 / "内幕·必涨·翻倍" — skip

## Compliance (inherited, must hold everywhere)
- No buy/sell/position advice; no point-target predictions in anything Scout produces or tags.
- Never fabricate sources or numbers. If a threshold can't be met honestly, report the shortfall — don't pad.

## Deliverables & working style
1. **First, a DESIGN DOC** covering the five open-design items, the **five fetcher performance/robustness points** above, the data-model mapping to `CITATION_CONTRACT.md`, and the module layout. **Stop and wait for my review before implementing.**
2. Then implement incrementally with tests. Include a **dry-run / fixtures mode** that runs extraction on saved HTML fixtures with no live network, so timestamp / quote / outlet-normalization logic is unit-testable offline.
3. Add a fixtures-based test for the **Verifier contract**: every quote's `span_start`/`span_end` must re-locate `text` inside `raw_content` exactly, and `context_before + text + context_after` must reconstruct.
4. **Ask clarifying questions before coding** wherever my requirements are ambiguous — especially on the data contract. Do not guess on the schema.
