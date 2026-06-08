# Primary-tracing Enrichment (cninfo) — Design

> **Read when:** picking up primary-tracing, or before the Verifier phase (which consumes `attached_primary_url` for I3).

**Status:** design approved 2026-06-08. Supersedes the P1a "full venue table is P2" note (in part) and unblocks the P2a live-floor gap.

## Problem

`build_pool` emits quotes with `attached_primary_url=None`. The grounded floor (`evaluate_floor`) requires `primary >= 1` (a quote carrying a primary URL), so on real data the floor **always fails** and `run_pipeline` emits a sub-floor status instead of publishing. Iron Law 3 ("NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE") is the invariant at stake.

The dangerous sub-problem: a *wrong* primary match launders a guess into "grounded fact" — worse than no match. The design defends against this with a number-level match-guard and a strict **attach-only-on-confirmation / no-attach-on-doubt** rule.

## Scope (locked decisions from brainstorm)

| # | Decision |
|---|---|
| Success bar | **A — mechanism-complete, offline-proven + one live smoke.** All logic unit-tested via injected seams; live wiring `# pragma: no cover`; one manual smoke proves the floor *can* clear on a real cninfo-backed pool. |
| Extraction | **C — hybrid.** Rules first (closed-set constituent match + keyword claim_type); DeepSeek fallback (injected seam) only when rules are inconclusive. Model picks *where to look*, never *what's true* — Law 4 safe. |
| Match-guard | **A — fetch-and-verify the number.** Fetch the candidate disclosure, confirm the quote's figure appears under tolerant numeric comparison; attach only on confirmed number. |
| Placement | **A — separate `enrich_primary` pass** after `build_pool`. `build_pool` untouched. |
| Venue scope | **A — cninfo only.** `exchange`/`regulator` route but find no live lookup → no attach (recorded gap). |

## Pipeline placement

```
gather (build_pool, UNCHANGED)  →  enrich_primary(sources, seams…)  →  evaluate_floor / run_pipeline
```

`enrich_primary` walks only `is_quantitative` quotes (Law 3 binds *quantitative* claims; non-quant quotes need no primary and are skipped). Per candidate quote, four steps, all behind injected seams:

1. **Extract `(claim_type, company)` — hybrid.**
   - *Rules first:* `company` = exact substring match of the quote text against the injected STAR50 constituent map (name → symbol code); `claim_type` = keyword table (募资/IPO → `fundraising`, 净利/营收/业绩/利润 → `earnings`, 减持 → `shareholding_reduction`, 政策/规/部委 → `policy`). First name hit wins; longest-name-first to avoid prefix collisions.
   - *DeepSeek fallback* (injected `classify` seam) only when rules yield no company OR no claim_type; returns the same `{claim_type, company}` enum (company must still resolve to a known symbol, else treated as unresolved → no attach).
2. **Route + look up** via existing `primary_venue_for(claim_type)`. If venue ≠ `cninfo` → **no attach** (B-deferred). Else injected `trace(claim_type, symbol, on_date)` returns a candidate disclosure URL or None.
3. **Match-guard — fetch-and-verify the number.** Injected `fetch(url)` returns disclosure text; confirm the quote's figure appears using the new amount-parser + tolerance (see below). **Attach only on confirmed number.** Any failure (no URL, unfetchable, number-not-found) → **no attach**.
4. **Attach** by rebuilding the frozen `Quote` with `attached_primary_url` set (Quote stays frozen; `dataclasses.replace`).

Every seam failure is non-fatal and degrades to *no attach* — one bad quote never aborts the pass. Quotes that are non-quantitative, or that fail any step, pass through with `attached_primary_url` unchanged (None).

## New building blocks

- **`scout/amount.py` (new): amount parser + tolerant matcher.** `numbers.py` only *detects* a quantity (`is_quantitative` → bool); it does not extract a value. New: `parse_amount(text) -> list[NormalizedAmount]` (digit + magnitude → a canonical numeric value in base units, plus percentage values), and `amount_matches(quote_text, disclosure_text, *, rel_tol) -> bool` (true iff some amount in the quote appears in the disclosure within `rel_tol`, handling unit/rounding divergence — 媒体 "3.6亿" ≈ filing "360,000,000元" ≈ "3.60亿元"). Reuses `numbers.py` magnitude vocabulary; does **not** modify `numbers.py`.
- **`scout/claim_extract.py` (new): rules classifier.** `extract_claim(text, constituents) -> ClaimRef | None` returning `(claim_type, symbol)` or None when rules are inconclusive. Pure, offline.
- **`scout/enrich.py` (new): the pass.** `enrich_primary(sources, *, classify, trace, fetch, constituents, on_date, rel_tol) -> list[Source]` — pure orchestration over injected seams. Plus `enrich_primary_live(conn, sources, *, on_date)` (`# pragma: no cover`) wiring `trace_to_primary` + Playwright fetch + a live constituent fetch. **The DeepSeek fallback seam is built and offline-proven, but `enrich_primary_live` stubs `classify` to `None` (rules-only end-to-end live) for this phase** — the closed STAR50 set means quotes almost always name the constituent, so the fallback (for unnamed references) is a YAGNI edge case; wiring the real DeepSeek call + its prompt-regression is a recorded follow-up.
- **Constituent map source (new, live).** `market.py` currently has no constituent list. Add a `# pragma: no cover` live fetcher (akshare STAR50 constituents → `{name: symbol}`); the offline pass receives the map as the injected `constituents` parameter.

## Data flow into `__main__` / live path

`gather_live` → `enrich_primary_live` → `evaluate_floor` → `run_pipeline`. The `__main__` entrypoint inserts the enrichment step between gather and the floor; the offline `run_once` tests are unaffected (they inject `gather` directly and can inject a pre-enriched pool).

## Error handling

- No company / no claim_type after rules+fallback → unresolved → no attach.
- Venue ≠ cninfo → no attach (recorded gap).
- `trace` returns None → no attach.
- `fetch` raises or returns empty → no attach (caught, logged, continue).
- Number not found within tolerance → no attach. **This is the guard that defends Law 3 — a deliberate wrong-number test must prove it bites.**
- The pass never raises on a single bad quote; it returns the full source list with whatever attachments succeeded.

## Testing (bar A)

Offline, injected seams, no DB/network:
- `amount.py`: parse cases (亿/万/元/%/个百分点), unit-divergence match (3.6亿 vs 360,000,000元), rounding tolerance, and a **wrong-number → no-match** case.
- `claim_extract.py`: each keyword → claim_type; constituent name → symbol; inconclusive → None.
- venue routing (existing `primary_venue_for` already tested).
- `enrich_primary`: happy path (quant quote → confirmed → attached); degraded paths (non-cninfo venue, trace None, fetch fail, number-mismatch) each → **no attach**; non-quant quote skipped; one bad quote doesn't abort the rest; DeepSeek fallback invoked only when rules inconclusive.
- One manual live smoke (owner-only, gitignored): real cninfo-backed pool clears the floor end-to-end.

## Out of scope / recorded gaps

- **Exchange + regulator venue lookups and their match-guards** — continues P1a's "full venue mapping table is P2". `shareholding_reduction` (exchange) is quantitative and will need this; `policy` (regulator) is qualitative. Their own phase.
- **The Verifier / I3 check that *consumes* `attached_primary_url`** — this phase *produces* the primary-URL data; the Verifier that enforces I3 over it is the separate P1b-deferred Verifier phase. No scope-creep into it here.
- **The real live DeepSeek fallback call** — `enrich_primary_live` stubs `classify` to `None` this phase (rules-only live). Wiring the real call + its prompt-regression is a follow-up.
- DeepSeek classifier prompt-regression tuning beyond a basic correctness test — the rules path carries the offline guarantee; the fallback is best-effort.
```
