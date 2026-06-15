# Scout primary-tracing recall — design

> **Read when:** working on Scout gather queries, claim extraction, or the cninfo primary-tracing seam (`query.py`, `claim_extract.py`, `primary.py`, `enrich.py`).

**Status:** approved 2026-06-15. Follows the live-floor diagnosis: `grounded=56 primary=0 outlets=8 passed=False` on 2026-06-12. Root cause was **gather recall**, not a code bug — the corpus was entirely macro index/flow commentary with no constituent-specific primary-traceable claim, so the `extract_claim` AND-gate (company ∧ keyword) yielded `both=0` and the floor correctly fail-closed.

## Goal

Make the live floor's `primary≥1` achievable on a normal trading day, via three coordinated recall changes:

1. **Pull company news into the corpus** (gather queries).
2. **Recognize more primary-traceable claim phrasings** (claim keywords).
3. **Let the amount-match guard pick the right disclosure** instead of testing only the first (multi-candidate trace — closes recorded gap **G1.4**).

## Non-goals (recorded, not silently dropped)

- **Non-cninfo venues** (exchange/regulator → `减持`/`政策`) — G1.2, no tracer yet. Pre-existing keywords for these stay but correctly yield no attach.
- **DeepSeek fallback classifier** — still stubbed to `None` (G1.1).
- **Per-name targeted gather queries** (the "top-movers" / "full per-constituent" options) — future enhancement if topical queries prove thin at smoke time.

## The binding constraint

A new claim keyword only lifts the floor's `primary` count if its claim_type **routes to cninfo** (the only built tracer) **and** a matching disclosure exists in the 90-day window. So keyword work targets the cninfo-traceable buckets only, and — because decision 3 below drops category filtering — all cninfo claim types trace identically, so **no new claim types are needed**: new synonyms fold into the existing `earnings`/`fundraising` buckets.

## Change 1 — Gather queries (`marketwind/scout/query.py`)

`build_recap_queries(prev_session)` keeps its 3 macro recap queries and **appends 3 topical event queries** anchored to the same `{月}月{日}日`:

- `科创50 成份股 {anchor} 业绩`
- `科创板 {anchor} 定增 募资 公告`
- `科创板 {anchor} 首发 IPO 新股`

~3 extra Bocha calls/run, no per-name enumeration. Surfaces constituent disclosures into the pool so `extract_claim` has company claims to match.

## Change 2 — Claim keywords (`marketwind/scout/claim_extract.py`)

Expand `_CLAIM_KEYWORDS` synonyms, folded into the existing cninfo-traceable types. **No new claim types.** Pre-existing `减持`→shareholding_reduction and `政策`/`部委`→policy entries stay untouched (surgical). First-hit-wins ordering preserved; place more-specific tokens before substrings they contain.

- **earnings:** 净利润, 净利, 利润, 营业收入, 营收, 业绩预告, 业绩快报, 业绩预增, 业绩预减, 业绩, 归母, 扣非, 年度报告, 年报, 一季报, 半年报, 三季报, 季报
- **fundraising:** 募集, 募资, 定向增发, 定增, 增发, 配股, 可转债, 再融资, IPO, 首发, 新股, 招股

(Existing first-hit table already has `减持` first; new tokens append after the existing earnings/fundraising tokens and before `政策`/`部委`. The exact ordering is a contract the implementer must preserve so substrings don't steal matches — e.g. `净利润` before `净利`, `业绩预告`/`业绩快报`/`业绩预增`/`业绩预减` before bare `业绩`.)

## Change 3 — Multi-candidate trace (`primary.py` + `enrich.py`) — closes G1.4

Today `trace_to_primary` returns a single URL (first disclosure) and `_resolve` amount-matches only that one, so a figure whose disclosure isn't the top hit misses. Fix:

**`marketwind/scout/primary.py`:**
- New `select_disclosure_urls(records: list[dict]) -> list[str]` — every non-empty `公告链接`, order preserved.
- `trace_to_primary(claim_type, company, on_date) -> list[str]` (was `str | None`): call akshare with **`category=""`**; return `select_disclosure_urls(...)` capped at **K=8**; `[]` when none/empty/not-cninfo.
- Remove now-dead `cninfo_category_for` + `_CNINFO_CATEGORY` (and `select_disclosure_url` singular).

**`marketwind/scout/enrich.py`:**
- `TraceFn = Callable[[str, str, date], Awaitable[list[str]]]`.
- `_resolve` iterates the candidate URLs: fetch each, `amount_matches`; return the **first** URL whose disclosure carries the number. A fetch error on one candidate skips to the next (does not abort). Returns `None` if no candidate matches. Iron Law 3 preserved — only a number-verified URL is ever attached.

## Locked contracts

| Symbol | Signature |
|---|---|
| `select_disclosure_urls` | `(records: list[dict]) -> list[str]` |
| `trace_to_primary` | `(claim_type: str, company: str, on_date) -> list[str]` |
| `TraceFn` | `Callable[[str, str, date], Awaitable[list[str]]]` |
| `_resolve` | iterate candidates, first amount-match wins, cap K=8, `None` if none match |

## Testing (offline)

- `test_claim_extract`: new synonyms map to the right bucket (e.g. `净利润`→earnings, `定增`→fundraising, `配股`→fundraising); substring ordering proven (`净利润` not mis-split).
- `test_primary`: `select_disclosure_urls` returns all non-empty links in order / skips empties / `[]` for empty input; drop `cninfo_category_for` + singular `select_disclosure_url` tests.
- `test_enrich`: `trace` seam returns a list; **key RED** — `_resolve` attaches the **2nd** candidate's URL when the 1st candidate's disclosure does NOT carry the number (proves iteration + amount-match discrimination), and returns `None` when no candidate matches.
- Live trace/fetch stay `# pragma: no cover`.

## Verification

Re-run live Stage 1 (`-m marketwind.scheduling --floor-only`) after merge; expect `primary≥1` on a day with real constituent disclosures. If still 0, the topical queries are too coarse → escalate to per-name targeted queries (recorded non-goal).
