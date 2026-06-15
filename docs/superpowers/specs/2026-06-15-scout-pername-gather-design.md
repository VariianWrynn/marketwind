# Per-name targeted gather queries — design

> **Read when:** working on Scout gather recall / the `query.py` + `gather.py` seam, or chasing why the live floor's `primary` count is 0.

**Status:** approved 2026-06-15. Follows the live-floor re-diagnosis: after the topical-query phase the floor read `grounded=405 primary=0 outlets=12 passed=False` on 2026-06-12. Root cause (evidence-backed, this session): the corpus is index/sector/flow commentary, so the `extract_claim` company∧keyword AND-gate never co-occurs — over 152 quantitative quotes, 31 carried a keyword and 11 carried a constituent name but **0 carried both in the same quote span**. The trace/fetch/amount-match stages never ran.

## Why this is the right fix (validation probe, this session)

A throwaway probe ran the real Bocha→Playwright→`extract_claim`→`trace_to_primary`→`amount_matches` chain on 3 names (中芯国际, 海光信息, 澜起科技) with per-name queries. Findings:

- Per-name queries **do** surface disclosure articles where name + keyword + number co-occur in one span — `extract_claim` (rules-only) resolved 6 such quotes. So **G1.1 (DeepSeek fallback) is not a prerequisite** for this path.
- The full chain reached `amount_matches=True` on 澜起科技's earnings — matching the **3rd** cninfo candidate, not the 1st, confirming the just-shipped G1.4 multi-candidate trace earns its keep.
- Two issues surfaced and are addressed below: **freshness skew** (undated per-name queries return historical profile pages → fix with a date anchor) and **aggregator-page noise** (quote-table sites yield spurious co-occurrences that **fail closed** at the amount-guard — safe, accepted).

## Goal

Lift the live floor's `primary` count off 0 on a normal trading day by surfacing that-day constituent disclosure coverage into the gather pool, so a quote span carries a constituent name + a primary keyword + a number that then traces to a number-verified cninfo primary. This unblocks the first real WeChat push (the floor must clear `primary≥1` to publish).

## Non-goals (recorded, not silently dropped)

- **Per-query result cap** — rely on the date anchor as the cost limiter for now; add a cap only if smoke runtime proves too long.
- **G1.1 DeepSeek fallback classifier** — still stubbed to `None`. Helps the sentence-split minority (name in one clause, number in the next) but the probe shows it is not required for the per-name path.
- **Fundraising / IPO per-name dimension** — earnings-only to start; the probe showed the fundraising dimension mostly added IPO-page noise. Add later if earnings-only proves thin.
- **Top-movers subset** — considered and rejected (needs a new akshare per-constituent price fetch + ranking, and misses a quiet discloser). All-50 chosen.

## Change 1 — new query builder (`marketwind/scout/query.py`)

Add `build_constituent_queries(names, prev_session)`: one date-anchored earnings query per constituent, anchor identical to the recap builder (`f"{prev_session.month}月{prev_session.day}日"`):

```
f"{name} {anchor} 业绩 净利润"
```

Single dimension (earnings). Empty `names` → empty list.

**Also drop the 3 coarse topical queries** from `build_recap_queries` (`科创50 成份股 {anchor} 业绩`, `科创板 {anchor} 定增 募资 公告`, `科创板 {anchor} 首发 IPO 新股`) — they were the coarse escalation that produced macro-flow noise but zero primary, now superseded by per-name. **Keep the 3 macro recap queries** (index-level grounded content + outlet diversity).

## Change 2 — compose in the pool builder (`marketwind/scout/gather.py`)

`build_pool` gains a keyword-only `names: list[str] = ()` parameter. Internally:

```
queries = build_recap_queries(prev_session) + build_constituent_queries(names, prev_session)
```

Default empty preserves existing offline `build_pool` tests. The dedup (`seen`), per-page fetch-skip, and empty-quotes-skip behaviour is unchanged, so aggregator noise pages still fail closed. `gather_live` passes `names=list(fetch_star50_constituents())` — the same constituent map `enrich_primary_live` already fetches.

## Change 3 — none to the funnel

`claim_extract.py`, `primary.py`, `enrich.py` are unchanged. `extract_claim` already maps name→symbol via the constituent map and the multi-candidate trace already iterates candidates; the probe confirmed the funnel end-to-end.

## Locked contracts

| Symbol | Signature |
|---|---|
| `build_constituent_queries` | `(names: list[str], prev_session: date) -> list[str]` |
| `build_recap_queries` | `(prev_session: date) -> list[str]` (now 3 macro queries; 3 topical removed) |
| `build_pool` | `build_pool(*, prev_session, names=(), search, fetch_page, parse, persist, now)` |

## Testing (offline)

- `test_query`: `build_constituent_queries(["中芯国际", "海光信息"], date(2026,6,12))` → `["中芯国际 6月12日 业绩 净利润", "海光信息 6月12日 业绩 净利润"]` (one anchored earnings query per name, order preserved); empty names → `[]`.
- `test_query`: `build_recap_queries(date(2026,6,12))` returns 3 queries and contains none of the 3 dropped topical strings (update the existing `test_queries_include_company_event_dimensions`).
- `test_gather`: `build_pool(..., names=["中芯国际"], search=<recording stub>, ...)` issues a query containing `中芯国际` (proves composition of recap + per-name through the seam).
- Live `gather_live` stays `# pragma: no cover`.

## Verification

Re-run live Stage 1 (`python -m marketwind.scheduling --floor-only`) after merge; expect `primary≥1` on a day with a real constituent disclosure. The probe already proved the chain reaches `amount_matches=True`, so a still-`0` result would point at that day genuinely having no in-window cninfo-traceable constituent disclosure (a calendar reality, not a code gap) → then consider the recorded follow-ups (fundraising dimension, G1.1).
