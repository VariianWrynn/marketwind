# Scout per-name targeted gather queries

> **Read when:** working on Scout gather recall, the `query.py` + `gather.py` seam, or chasing why the live floor's `primary` count is 0.

**Status:** complete, 2026-06-15. Spec: `docs/superpowers/specs/2026-06-15-scout-pername-gather-design.md`. Plan: `docs/superpowers/plans/2026-06-15-scout-pername-gather.md`.

**Why:** after the primary-tracing-recall phase the live floor still read `grounded=405 primary=0 outlets=12 passed=False`. Re-diagnosis (systematic-debugging Phase 1, per-stage instrumentation) found the root cause is **gather recall**, not a code bug: over 152 quantitative quotes, 31 carried a claim keyword and 11 carried a constituent name, but **0 carried both in the same quote span**, so the `extract_claim` company∧keyword AND-gate never fired and the trace/fetch/amount-match stages never ran. The corpus was macro index/sector/flow commentary. A throwaway probe confirmed per-name queries surface that-day disclosure articles where name + keyword + number co-occur, and the chain reaches `amount_matches=True` (on the 3rd cninfo candidate — exercising the just-shipped G1.4 multi-candidate trace). This phase lifts recall so `primary≥1` is achievable, unblocking the first real WeChat push.

## What was done, by task

| Task | Module | What it does | Commit |
|---|---|---|---|
| 1 | `scout/query.py` | add `build_constituent_queries(names, prev_session)` → one date-anchored earnings query per constituent (`{name} {anchor} 业绩 净利润`); empty names → `[]` | 37d1584 |
| 2 | `scout/query.py` | drop the 3 coarse topical recap queries (业绩 / 定增募资 / 首发IPO), superseded by per-name; keep the 3 macro recap queries | 4e178ed |
| 3 | `scout/gather.py` | `build_pool` gains keyword-only `names: list[str] = ()`, composes `build_recap_queries(...) + build_constituent_queries(...)`; `gather_live` wires `fetch_star50_constituents()` | f53178f |

## Key invariants proved here

- **Composition, not replacement:** `test_build_pool_issues_per_name_queries` asserts both a per-name query (`中芯国际`) AND a macro recap query (`收盘 复盘`) are issued to `search` — the per-name set is added after the recap set, not swapping it.
- **Default preserves old behavior:** `names: list[str] = ()` defaults empty; the 4 pre-existing `build_pool` tests call without `names` and stay green, so existing offline gather behavior is untouched.
- **Fail-closed preserved:** the dedup / per-page fetch-skip / empty-quotes-skip loop is byte-for-byte unchanged, so aggregator-page noise still dies at the `amount_matches` guard (no fabricated attach). Iron Law 3 intact.
- **Anchor identical to recap:** the date anchor is `f"{prev_session.month}月{prev_session.day}日"`, the same literal the recap builder uses — the date anchor is the cost limiter (no per-query cap by design).

## How to test

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q \
  tests/scout/test_query.py tests/scheduling/test_gather.py   # 11 tests
```

All pure logic is unit-tested offline; `gather_live` stays `# pragma: no cover - live`.

## Out of scope / still open

- **Live verification (owner-run):** re-run Stage 1 (`python -m marketwind.scheduling --floor-only`) on a day with a real constituent disclosure; expect `primary≥1`. G0.3 simulated-clock limitation applies — a still-`0` result on a quiet calendar day is a disclosure-availability reality, not a code gap.
- **Recorded follow-ups** if earnings-only proves thin: fundraising/IPO per-name dimension; **G1.1** DeepSeek fallback classifier (still stubbed `None`); per-query result cap (only if smoke runtime proves too long).
- **Pre-existing infra failure (not from this phase):** `tests/scout/test_cninfo_pdf.py::test_integration_pdf_number_match_attaches_primary` fails identically at the pre-session commit `68ee729` — a PDF-text-extraction environment issue, unrelated to this seam.
