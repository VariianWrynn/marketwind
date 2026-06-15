# Per-name Targeted Gather Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface that-day STAR50 constituent disclosure coverage into the gather pool (one date-anchored earnings query per constituent) so `extract_claim`'s company∧keyword AND-gate co-occurs and the live floor's `primary` count clears ≥1 — unblocking the first real WeChat push.

**Architecture:** Add a new query builder `build_constituent_queries(names, prev_session)` in `query.py`; drop the 3 superseded coarse topical queries from `build_recap_queries`; compose both lists in `build_pool` via a new `names=()` param; wire `gather_live` to pass the live constituent map. The funnel (`claim_extract`/`primary`/`enrich`) is unchanged — a validation probe this session confirmed it traces end-to-end (incl. a 3rd-candidate `amount_matches=True`).

**Tech Stack:** Python 3.11, pytest (`asyncio_mode=auto`), akshare (live constituent map), Bocha + Playwright (live gather, `# pragma: no cover`).

**Spec:** `docs/superpowers/specs/2026-06-15-scout-pername-gather-design.md`

**Execution notes (CLAUDE.md altitude):** Test code below is near-verbatim — the RED assertion is the contract and must fail on an *assertion* (not ImportError/collection error) for the stated reason. Implementation is described in prose + exact signatures/literals; the implementer writes the body against the real file. Windows run prefix: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider`.

**Locked contracts (consistent across all tasks):**

| Symbol | Signature / shape |
|---|---|
| `build_constituent_queries` | `(names: list[str], prev_session: date) -> list[str]` — one `f"{name} {anchor} 业绩 净利润"` per name, order preserved, `[]` for empty |
| `build_recap_queries` | `(prev_session: date) -> list[str]` — exactly 3 macro recap queries (topical removed) |
| `build_pool` | `build_pool(*, prev_session, names: list[str] = (), search, fetch_page, parse, persist, now)` — queries = recap + constituent |
| anchor literal | `f"{prev_session.month}月{prev_session.day}日"` (e.g. `6月12日`) |

---

### Task 1: `build_constituent_queries` (new query builder)

**Files:**
- Modify: `marketwind/scout/query.py`
- Test: `tests/scout/test_query.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/scout/test_query.py` (keep the existing `from datetime import date` and `build_recap_queries` imports; add `build_constituent_queries` to the import line so it reads `from marketwind.scout.query import build_constituent_queries, build_recap_queries`):

```python
def test_constituent_queries_one_anchored_earnings_query_per_name():
    qs = build_constituent_queries(["中芯国际", "海光信息"], date(2026, 6, 12))
    assert qs == [
        "中芯国际 6月12日 业绩 净利润",
        "海光信息 6月12日 业绩 净利润",
    ]


def test_constituent_queries_empty_names_is_empty():
    assert build_constituent_queries([], date(2026, 6, 12)) == []
```

- [ ] **Step 2: Run the test, watch it fail on the assertion**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py::test_constituent_queries_one_anchored_earnings_query_per_name -v`
Expected: FAIL. First it will be an ImportError (function absent) — to get a true assertion RED, first add a stub `def build_constituent_queries(names, prev_session): return []` to `query.py`, re-run, and watch it fail as `AssertionError: assert [] == ['中芯国际 6月12日 业绩 净利润', ...]`. That asserts the builder actually emits per-name anchored queries.

- [ ] **Step 3: Implement**

In `marketwind/scout/query.py`, implement `build_constituent_queries(names: list[str], prev_session: date) -> list[str]`: compute `anchor = f"{prev_session.month}月{prev_session.day}日"` (identical to `build_recap_queries`), and return `[f"{name} {anchor} 业绩 净利润" for name in names]`. Single earnings dimension; order preserved; empty `names` naturally yields `[]`.

- [ ] **Step 4: Run both new tests, confirm pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py -v`
Expected: PASS (the two new tests green; the existing recap tests still green at this point).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/query.py tests/scout/test_query.py
git commit -m "feat(scout): add build_constituent_queries (per-name anchored earnings query)"
```

---

### Task 2: Drop the 3 superseded coarse topical queries from `build_recap_queries`

**Files:**
- Modify: `marketwind/scout/query.py:8-17` (the `build_recap_queries` return list)
- Test: `tests/scout/test_query.py:22-31` (retarget `test_queries_include_company_event_dimensions`)

Context: `build_recap_queries` currently returns 6 queries — 3 macro recap (lines 11-13) + 3 topical (lines 14-16: `科创50 成份股 {anchor} 业绩`, `科创板 {anchor} 定增 募资 公告`, `科创板 {anchor} 首发 IPO 新股`). The 3 topical are the coarse escalation that produced macro-flow noise but zero primary; per-name (Task 1) supersedes them. Remove them. The existing test `test_queries_include_company_event_dimensions` asserts those topical tokens are present, so it must be retargeted to assert their **absence** and that exactly 3 queries remain.

- [ ] **Step 1: Retarget the test to the new contract (this is the RED)**

Replace the whole `test_queries_include_company_event_dimensions` function (currently `tests/scout/test_query.py:22-31`) with:

```python
def test_recap_queries_are_macro_only_no_topical_event_dims():
    qs = build_recap_queries(date(2026, 5, 29))
    # the 3 coarse topical queries were superseded by per-name constituent
    # queries (build_constituent_queries) and must no longer be emitted here
    assert len(qs) == 3
    joined = " ".join(qs)
    assert "成份股" not in joined
    assert "定增" not in joined and "募资" not in joined
    assert "IPO" not in joined and "首发" not in joined
```

Leave `test_queries_have_date_anchors` and `test_queries_cover_recap_dimension` unchanged — the 3 macro recap queries still satisfy them.

- [ ] **Step 2: Run it, watch it fail on the assertion**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py::test_recap_queries_are_macro_only_no_topical_event_dims -v`
Expected: FAIL as `AssertionError: assert 6 == 3` (topical still present). This pins that the topical queries are gone.

- [ ] **Step 3: Implement — remove the 3 topical lines**

In `marketwind/scout/query.py`, edit `build_recap_queries` so its return list is exactly the 3 macro recap queries:

```python
    return [
        f"科创50 {anchor} 收盘 复盘",
        f"科创50指数 上一交易日 涨跌幅 成交额",
        f"科创板 权重股 {anchor} 表现",
    ]
```

(Delete the `成份股 … 业绩`, `定增 募资 公告`, and `首发 IPO 新股` lines. `build_constituent_queries` is untouched.)

- [ ] **Step 4: Run the full query test module, confirm pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py -v`
Expected: PASS (retargeted test green; `test_queries_have_date_anchors`, `test_queries_cover_recap_dimension`, and Task 1's two tests all green).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/query.py tests/scout/test_query.py
git commit -m "feat(scout): drop coarse topical recap queries, superseded by per-name"
```

---

### Task 3: Compose per-name queries in `build_pool` + wire `gather_live`

**Files:**
- Modify: `marketwind/scout/gather.py:24-45` (`build_pool` signature + query composition) and `:54-85` (`gather_live` wiring)
- Test: `tests/scheduling/test_gather.py`

Context: `build_pool` (currently `tests/scheduling/test_gather.py` exercises it) builds `queries = build_recap_queries(prev_session)` then loops search→fetch→parse→persist with `seen`-dedup. We add a keyword-only `names: list[str] = ()` param and append `build_constituent_queries(names, prev_session)`. Default empty preserves the 4 existing `build_pool` tests (they call without `names`). `gather_live` passes the live constituent names.

- [ ] **Step 1: Write the failing test**

Append to `tests/scheduling/test_gather.py`:

```python
async def test_build_pool_issues_per_name_queries():
    asked: list[str] = []

    async def _recording_search(query: str):
        asked.append(query)
        return []  # no hits → no fetch; we only care which queries are issued

    store = []
    await build_pool(prev_session=_PREV, names=["中芯国际"],
                     search=_recording_search, fetch_page=_fetch_ok,
                     parse=_parse_one_quote, persist=_persist_recorder(store),
                     now=_NOW)
    joined = " ".join(asked)
    assert "中芯国际" in joined          # per-name query reached the search seam
    assert any("收盘 复盘" in q for q in asked)  # macro recap queries still issued
```

- [ ] **Step 2: Run it, watch it fail on the assertion**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scheduling/test_gather.py::test_build_pool_issues_per_name_queries -v`
Expected: FAIL. `build_pool` does not yet accept `names`, so first add the param as an accepted-but-unused `names: list[str] = ()` to get past the TypeError, re-run, and watch it fail as `AssertionError` on `assert "中芯国际" in joined` (the per-name query is never issued because composition isn't wired). That pins the composition behavior, not just the signature.

- [ ] **Step 3: Implement the composition + wiring**

In `marketwind/scout/gather.py`:
1. Add `build_constituent_queries` to the import from `marketwind.scout.query` (alongside `build_recap_queries`).
2. Change `build_pool`'s signature to add a keyword-only `names: list[str] = ()` (place it after `prev_session`, before `search`).
3. Change the first line of the body from `queries = build_recap_queries(prev_session)` to `queries = build_recap_queries(prev_session) + build_constituent_queries(names, prev_session)`. Everything else (dedup, fetch-skip, empty-skip, persist) is unchanged.
4. In `gather_live` (`# pragma: no cover - live`), fetch the constituent map and pass its names: add `from marketwind.scout.market import fetch_star50_constituents`, compute `names = list(fetch_star50_constituents())` before the `build_pool` call, and pass `names=names` into `build_pool(...)`.

- [ ] **Step 4: Run the gather test module, confirm pass**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scheduling/test_gather.py -v`
Expected: PASS (new composition test green; the 4 existing `build_pool` tests still green because `names` defaults to `()`).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/gather.py tests/scheduling/test_gather.py
git commit -m "feat(scout): build_pool composes per-name queries; gather_live wires constituents"
```

---

### Task 4: Full-suite verification + progress note + spec/GAPS bookkeeping

**Files:**
- Create: `docs/progress/scout-pername-gather.md`
- Modify: `docs/GAPS.md` (note the primary-recall escalation landed)

- [ ] **Step 1: Run the full offline suite**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`
Expected: the same pre-existing infra failures only (DB `ConnectionRefusedError` in `test_repo`/`test_run_ledger`/`test_record_failures`/`test_repo_writer`, `test_health`, `test_migrate`, and `test_cninfo_pdf` integration) — **no new failures** in `tests/scout/test_query.py` or `tests/scheduling/test_gather.py`. Confirm the touched modules are green:
`PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q tests/scout/test_query.py tests/scheduling/test_gather.py`
Expected: all pass.

- [ ] **Step 2: Write the progress note**

Create `docs/progress/scout-pername-gather.md` (lightweight — title + Read-when + a task/commit table + invariants-proved bullets, mirroring `docs/progress/scout-primary-tracing-recall.md`). Record: the AND-gate root cause (31 keyword-only + 11 name-only + 0 co-occur over 152 quant quotes), the validation probe result (per-name queries produced 6 co-occurring extractable quotes, one reaching `amount_matches=True` on the 3rd cninfo candidate), the 3 commits, and the open follow-ups (per-query cap, fundraising dimension, G1.1).

- [ ] **Step 3: Note the escalation in GAPS.md**

In `docs/GAPS.md`, under the "Recently closed" section, append a bullet recording that the per-name targeted gather escalation landed (the recall fix the topical-query phase's verification note pointed to). Do not alter G1.1/G1.2 (still open).

- [ ] **Step 4: Commit**

```bash
git add docs/progress/scout-pername-gather.md docs/GAPS.md
git commit -m "docs: per-name gather progress note + GAPS escalation record"
```

- [ ] **Step 5: Live verification (owner-run, recorded — not a code step)**

Re-run `python -m marketwind.scheduling --floor-only` on a day with a real constituent disclosure; expect `primary≥1`. A still-`0` result with these queries points at that day having no in-window cninfo-traceable disclosure (calendar reality) → consider the recorded follow-ups.

---

## Self-Review

**Spec coverage:** Change 1 (new builder) → Task 1; Change 1 (drop topical) → Task 2; Change 2 (build_pool compose + gather_live) → Task 3; Change 3 (no funnel changes) → respected (no task touches claim_extract/primary/enrich); Testing section → Tasks 1-3 tests; Verification → Task 4 Step 5. All spec sections covered.

**Placeholder scan:** No TBD/TODO; every code step shows exact code or exact signature+literal; the anchor literal and query format are spelled out; commands are concrete with expected output.

**Type consistency:** `build_constituent_queries(names, prev_session)` signature identical in Tasks 1 and 3; `build_pool(..., names=())` identical in Task 3 test and impl; anchor literal `f"{prev_session.month}月{prev_session.day}日"` consistent with `build_recap_queries`. The Task 1 query string `"中芯国际 6月12日 业绩 净利润"` matches the format `f"{name} {anchor} 业绩 净利润"` used in the impl step.
