# Scout primary-tracing recall

> **Read when:** working on Scout gather recall, claim-keyword coverage, or the cninfo primary-tracing seam (`query.py`, `claim_extract.py`, `primary.py`, `enrich.py`).

**Status:** complete, 2026-06-15. Spec: `docs/superpowers/specs/2026-06-15-scout-primary-tracing-recall-design.md`. Plan: `docs/superpowers/plans/2026-06-15-scout-primary-tracing-recall.md`.

**Why:** the live floor returned `grounded=56 primary=0 outlets=8 passed=False` on 2026-06-12. Root cause was **gather recall**, not a code bug — the corpus was entirely macro index/flow commentary with zero constituent-specific primary-traceable claims, so the `extract_claim` company∧keyword AND-gate yielded `both=0` and the floor correctly fail-closed. This phase lifts recall on three coordinated seams so `primary≥1` is achievable on a normal trading day; it closes recorded gap **G1.4** (multi-candidate trace).

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `scout/query.py` | append 3 topical constituent-event queries (业绩 / 定增募资 / 首发IPO) to the date-anchored recap set | dc9b3f0 |
| 2 | `scout/claim_extract.py` | fold cninfo-traceable keyword synonyms into existing `earnings`/`fundraising` buckets; first-hit ordering preserved (longer substrings first) | 1e64392 |
| 3 | `scout/primary.py` | `select_disclosure_urls` (all non-empty 公告链接, order-preserved); `trace_to_primary` returns a **list**, `category=""`, K=8 cap; drop dead `cninfo_category_for`/`_CNINFO_CATEGORY`/singular helper | 6186577 |
| 4 | `scout/enrich.py` | `TraceFn` returns `list[str]`; `_resolve` iterates candidates, attaches the **first** whose disclosure the amount-guard confirms; fetch error on one skips to next | 51ce25b |

## Key invariants proved here

- **Iron Law 3 preserved:** only a number-verified URL ever attaches. Multi-candidate iteration tries each disclosure but still attaches only on an `amount_matches` confirmation — proven by `test_resolve_picks_second_candidate_when_first_mismatches` (the 1st candidate's wrong figure is rejected, the 2nd's match attaches) and `test_resolve_none_when_no_candidate_matches`.
- **Fails closed:** empty candidate list, all-mismatch, and per-candidate fetch error all degrade to no-attach, never fabricate.
- **No new claim types:** synonyms route through the existing cninfo-traceable buckets, so the venue map and `amount_matches` guard are untouched.
- **Keyword ordering contract:** more-specific tokens precede the substrings they contain (e.g. `净利润` before bare `利润`, `业绩预告`/`业绩快报`/`业绩预增`/`业绩预减` before bare `业绩`) so first-hit-wins does not mis-split.

## How to test

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q \
  tests/scout/test_query.py tests/scout/test_claim_extract.py \
  tests/scout/test_primary.py tests/scout/test_enrich.py   # 40 tests
```

All pure logic is unit-tested offline; the live trace/fetch paths stay `# pragma: no cover`.

## Out of scope / still open

- **G1.1** DeepSeek fallback classifier still stubbed to `None` (rules-only live).
- **G1.2** non-cninfo venues (exchange `减持` / regulator `政策`) still have no tracer — their keywords stay but correctly yield no attach.
- **Per-name targeted gather queries** — future escalation if the 3 topical queries prove too coarse at live smoke time.
- **Live verification:** re-run Stage 1 (`-m marketwind.scheduling --floor-only`) on a day with real constituent disclosures; expect `primary≥1`. Owner-run (G0.3 simulated-clock limitation applies).
