# Scout Primary-Tracing Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live floor's `primary≥1` achievable by pulling company news into the corpus, recognizing more primary-traceable claim phrasings, and letting the amount-match guard pick the right disclosure from a candidate list (closes gap G1.4).

**Architecture:** Three coordinated Scout changes. (1) `query.py` appends topical event queries so constituent disclosures enter the pool. (2) `claim_extract.py` expands `_CLAIM_KEYWORDS` synonyms folded into the existing `earnings`/`fundraising` buckets. (3) `primary.py`'s `trace_to_primary` returns a *list* of candidate disclosure URLs (drops category filtering), and `enrich.py`'s `_resolve` iterates them, attaching the first whose disclosure carries the quote's number. Iron Law 3 preserved — only a number-verified URL is ever attached.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode=auto`), akshare (live, `# pragma: no cover`), existing `amount_matches` guard.

**Spec:** `docs/superpowers/specs/2026-06-15-scout-primary-tracing-recall-design.md`

**Run python as:** `.venv/Scripts/python.exe` with `PYTHONPATH=.` from `D:/AgentDaily`. Use `-p no:cacheprovider` to avoid cache noise.

---

## Locked contracts (cross-task consistency — do not drift)

| Symbol | File | Signature |
|---|---|---|
| `build_recap_queries` | `marketwind/scout/query.py` | `(prev_session: date) -> list[str]` (unchanged sig; returns 6 queries now) |
| `_CLAIM_KEYWORDS` | `marketwind/scout/claim_extract.py` | `list[tuple[str, str]]` (keyword, claim_type); first-hit-wins, longer substrings first |
| `select_disclosure_urls` | `marketwind/scout/primary.py` | `(records: list[dict]) -> list[str]` |
| `trace_to_primary` | `marketwind/scout/primary.py` | `(claim_type: str, company: str, on_date) -> list[str]` |
| `TraceFn` | `marketwind/scout/enrich.py` | `Callable[[str, str, date], Awaitable[list[str]]]` |
| `_resolve` | `marketwind/scout/enrich.py` | iterate candidate URLs; first amount-match wins; per-candidate fetch error skips; `None` if none match |

**Removed (dead under the no-category-filter decision):** `cninfo_category_for`, `_CNINFO_CATEGORY`, `select_disclosure_url` (singular) — and their tests.

---

## Task 1: Topical gather queries

**Files:**
- Modify: `marketwind/scout/query.py`
- Test: `tests/scout/test_query.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/scout/test_query.py`:

```python
def test_queries_include_company_event_dimensions():
    qs = build_recap_queries(date(2026, 5, 29))
    joined = " ".join(qs)
    # corpus must now reach company-level primary events, not just index recap
    assert "业绩" in joined
    assert "募资" in joined or "定增" in joined
    assert "IPO" in joined or "首发" in joined
    # new event queries stay date-anchored
    assert "成份股" in joined or "科创板" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py::test_queries_include_company_event_dimensions -v`
Expected: FAIL on `assert "业绩" in joined` (current queries are macro-only; `业绩`/`募资`/`IPO` absent).

- [ ] **Step 3: Implement**

In `build_recap_queries`, keep the 3 existing macro recap queries and append 3 topical event queries anchored to the same `anchor = f"{prev_session.month}月{prev_session.day}日"`. The appended queries, exactly:

```python
        f"科创50 成份股 {anchor} 业绩",
        f"科创板 {anchor} 定增 募资 公告",
        f"科创板 {anchor} 首发 IPO 新股",
```

Do not alter the 3 existing queries.

- [ ] **Step 4: Run the query tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_query.py -v`
Expected: PASS (4 tests — the 3 pre-existing + the new one; the existing date-anchor test still holds because every new query contains the `{月}月{日}日` anchor).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/query.py tests/scout/test_query.py
git commit -m "feat(scout): add topical company-event gather queries (recall)"
```

---

## Task 2: Expand claim keyword synonyms

**Files:**
- Modify: `marketwind/scout/claim_extract.py`
- Test: `tests/scout/test_claim_extract.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/scout/test_claim_extract.py`:

```python
import pytest

@pytest.mark.parametrize("text,expected_type", [
    ("中芯国际净利润3.6亿元", "earnings"),
    ("中芯国际营业收入12亿元", "earnings"),
    ("中芯国际业绩预告超预期", "earnings"),
    ("中芯国际三季报披露", "earnings"),
    ("澜起科技定增募集10亿元", "fundraising"),
    ("澜起科技拟配股", "fundraising"),
    ("澜起科技发行可转债", "fundraising"),
    ("澜起科技首发上市", "fundraising"),
])
def test_expanded_synonyms_route_to_bucket(text, expected_type):
    assert extract_claim(text, CONS).claim_type == expected_type


def test_net_profit_not_missplit_by_substring():
    # 净利润 must win over the shorter 净利 (both earnings, but proves ordering
    # is intact so a future shorter token can't steal a longer match)
    assert extract_claim("中芯国际净利润3.6亿元", CONS).claim_type == "earnings"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_claim_extract.py::test_expanded_synonyms_route_to_bucket -v`
Expected: FAIL — current `_CLAIM_KEYWORDS` lacks `营业收入`, `业绩预告`, `三季报`, `定增`, `配股`, `可转债`, `首发` (the `营业收入`/`配股`/etc. cases return `None` → `AttributeError` on `.claim_type`, or assertion mismatch). Confirm at least one case fails on the synonym being absent, not a collection error.

- [ ] **Step 3: Implement**

Replace `_CLAIM_KEYWORDS` with the expanded table below. **Ordering is a contract:** within a claim_type, any token that is a substring of another must come *after* the longer one (first-hit-wins). Keep `减持` first and `政策`/`部委` last (pre-existing, untouched). Keep fundraising before earnings (pre-existing cross-bucket precedence).

```python
_CLAIM_KEYWORDS: list[tuple[str, str]] = [
    ("减持", "shareholding_reduction"),
    # fundraising (cninfo-traceable)
    ("募集", "fundraising"),
    ("募资", "fundraising"),
    ("定向增发", "fundraising"),
    ("定增", "fundraising"),
    ("增发", "fundraising"),
    ("配股", "fundraising"),
    ("可转债", "fundraising"),
    ("再融资", "fundraising"),
    ("IPO", "fundraising"),
    ("首发", "fundraising"),
    ("新股", "fundraising"),
    ("招股", "fundraising"),
    # earnings (cninfo-traceable)
    ("净利润", "earnings"),
    ("净利", "earnings"),
    ("营业收入", "earnings"),
    ("营收", "earnings"),
    ("业绩预告", "earnings"),
    ("业绩快报", "earnings"),
    ("业绩预增", "earnings"),
    ("业绩预减", "earnings"),
    ("业绩", "earnings"),
    ("利润", "earnings"),
    ("归母", "earnings"),
    ("扣非", "earnings"),
    ("年度报告", "earnings"),
    ("年报", "earnings"),
    ("一季报", "earnings"),
    ("半年报", "earnings"),
    ("三季报", "earnings"),
    ("季报", "earnings"),
    # policy (venue not yet built — kept, correctly yields no attach)
    ("政策", "policy"),
    ("部委", "policy"),
]
```

Do not change `_match_company`, `_match_claim_type`, `extract_claim`, or `ClaimRef`.

- [ ] **Step 4: Run the claim-extract tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_claim_extract.py -v`
Expected: PASS (all pre-existing 5 tests + the new parametrized + ordering test). The pre-existing `test_shareholding_reduction_keyword` still passes (`减持` retained first).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/claim_extract.py tests/scout/test_claim_extract.py
git commit -m "feat(scout): expand earnings/fundraising claim keyword synonyms (recall)"
```

---

## Task 3: List-returning trace + drop category filter

**Files:**
- Modify: `marketwind/scout/primary.py`
- Test: `tests/scout/test_primary.py`

- [ ] **Step 1: Write the failing test**

In `tests/scout/test_primary.py`: change the import line to drop `cninfo_category_for, select_disclosure_url` and add `select_disclosure_urls`:

```python
from marketwind.scout.primary import primary_venue_for, select_disclosure_urls, disclosure_window
```

Delete the `--- cninfo_category_for ---` block (the `test_cninfo_category_for` parametrize) and the four `test_select_disclosure_url_*` tests. Add:

```python
# --- select_disclosure_urls ---

def test_select_disclosure_urls_returns_all_in_order():
    records = [{"公告链接": "http://a"}, {"公告链接": "http://b"}]
    assert select_disclosure_urls(records) == ["http://a", "http://b"]


def test_select_disclosure_urls_skips_empty_and_missing_keys():
    records = [{"公告链接": ""}, {"other": "x"}, {"公告链接": "http://c"}]
    assert select_disclosure_urls(records) == ["http://c"]


def test_select_disclosure_urls_empty_list():
    assert select_disclosure_urls([]) == []
```

Keep `test_claim_type_routes_to_venue`, `test_unknown_claim_type_returns_none`, and `test_disclosure_window_90_day_lookback` unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_primary.py::test_select_disclosure_urls_returns_all_in_order -v`
Expected: FAIL with `ImportError: cannot import name 'select_disclosure_urls'` — then (this is a behavioral function) immediately scaffold a stub returning a wrong sentinel so the assertion itself fails: add `def select_disclosure_urls(records): return []` temporarily, re-run, and confirm it fails on `assert [] == ["http://a", "http://b"]` (assertion RED, not import RED).

- [ ] **Step 3: Implement**

In `marketwind/scout/primary.py`:

1. Add `select_disclosure_urls(records: list[dict]) -> list[str]` — return every non-empty `公告链接` value (as `str`), order preserved; empties and missing keys skipped.
2. Change `trace_to_primary` to return `list[str]`: keep the venue guard (`if venue != "cninfo": return []`), call akshare with `category=""` (drop `cninfo_category_for`), and on a non-empty DataFrame return `select_disclosure_urls(df.to_dict("records"))[:8]` (the **K=8** cap — a live safeguard); return `[]` when `df is None or df.empty`. Update its return annotation to `-> list[str]` and keep the `# pragma: no cover - live` marker.
3. Delete `cninfo_category_for`, the `_CNINFO_CATEGORY` dict, and the singular `select_disclosure_url`.

Leave `primary_venue_for`, `_VENUE`, and `disclosure_window` unchanged.

- [ ] **Step 4: Run the primary tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_primary.py -v`
Expected: PASS (venue routing + 3 new `select_disclosure_urls` + window). No reference to the deleted symbols remains.

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/primary.py tests/scout/test_primary.py
git commit -m "feat(scout): trace_to_primary returns candidate list, drop category filter (G1.4)"
```

---

## Task 4: Iterate candidates in _resolve

**Files:**
- Modify: `marketwind/scout/enrich.py`
- Test: `tests/scout/test_enrich.py`

- [ ] **Step 1: Write the failing test**

First, **update every existing `trace` seam** in `tests/scout/test_enrich.py` to the new list contract: each `return "https://cninfo.com.cn/d1"` becomes `return ["https://cninfo.com.cn/d1"]`, and in `test_trace_none_does_not_attach` the body becomes `return []`. (`_never_trace` is unchanged — it raises.) These edits keep the 9 existing tests valid under the new contract.

Then add the new multi-candidate tests:

```python
async def test_resolve_picks_second_candidate_when_first_mismatches():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        return "本期净利润为5亿元" if url.endswith("d1") else "本期净利润为3.6亿元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d2"


async def test_resolve_none_when_no_candidate_matches():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        return "本期净利润为9亿元"  # neither carries 3.6亿

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_resolve_empty_candidate_list_no_attach():
    async def trace(ct, sym, on_date):
        return []

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace,
                               fetch=_never_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_resolve_skips_candidate_whose_fetch_errors():
    async def trace(ct, sym, on_date):
        return ["https://cninfo.com.cn/d1", "https://cninfo.com.cn/d2"]

    async def fetch(url):
        if url.endswith("d1"):
            raise RuntimeError("pdf 500")
        return "本期净利润为3.6亿元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_enrich.py::test_resolve_picks_second_candidate_when_first_mismatches -v`
Expected: FAIL — current `_resolve` does `url = await trace(...)` then treats the **list** as a single URL: `if not url` is False for a non-empty list, then `fetch(["...","..."])` is called with a list and `amount_matches` runs against `d1`'s text only, so the assertion `== ".../d2"` fails (or fetch mishandles the list). Confirm the RED is the wrong-candidate/assertion, not a collection error.

- [ ] **Step 3: Implement**

Change `marketwind/scout/enrich.py`:

1. `TraceFn = Callable[[str, str, date], Awaitable[list[str]]]`.
2. Rewrite the trace→fetch→match tail of `_resolve` to iterate candidates. Behavioral contract (write the body to match, do not copy verbatim):
   - keep the early returns (`not is_quantitative`, `ref is None` after extract+classify, non-cninfo venue) exactly as they are;
   - wrap the `trace(...)` call in `try/except Exception: return None` (a trace failure still degrades safely);
   - iterate the returned candidate URLs in order; for each, `try: disclosure = await fetch(url) except Exception: continue`; if `amount_matches(quote.text, disclosure, rel_tol=rel_tol)` is True, `return url`;
   - after the loop with no match, `return None`.
3. `enrich_primary_live._trace` already `return await trace_to_primary(...)`, which now yields a list — no change needed there beyond it being correctly typed.

Do not change `enrich_primary` (the per-source loop), `_classify` stub, or the live fetch wiring.

- [ ] **Step 4: Run the enrich tests**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/scout/test_enrich.py -v`
Expected: PASS — all 9 updated pre-existing tests + 4 new ones. In particular `test_one_bad_quote_does_not_abort_rest` still holds (quote-1's single candidate fetch raises → skipped → None; quote-2's fetch succeeds → attach).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/enrich.py tests/scout/test_enrich.py
git commit -m "feat(scout): _resolve iterates candidate disclosures, amount-match wins (G1.4)"
```

---

## Task 5: Progress note + full-suite verification

**Files:**
- Create: `docs/progress/scout-primary-tracing-recall.md`
- Modify: `docs/GAPS.md` (mark G1.4 closed)

- [ ] **Step 1: Run the full offline suite**

Run: `PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q`
Expected: all green (no regressions from the trace contract change). If any non-scout test referenced the removed symbols, fix the reference (there should be none — grep confirmed usage was confined to `primary.py` + `test_primary.py`).

- [ ] **Step 2: Update GAPS.md**

In `docs/GAPS.md`, mark the **G1.4** row resolved (note: "closed 2026-06-15 — `trace_to_primary` returns candidate list; `_resolve` amount-matches each. See `docs/progress/scout-primary-tracing-recall.md`."). Leave G1.1 (DeepSeek classifier stub) and G1.2 (non-cninfo venues) open.

- [ ] **Step 3: Write the progress note**

Create `docs/progress/scout-primary-tracing-recall.md` with the lightweight template (title + `> Read when:` line + a task/commit table + a short "invariants proved" bullet list): the three recall changes, the commits, the G1.4 closure, and the preserved Iron Law 3 invariant (only number-verified URLs attach). Note the recorded non-goals (G1.1/G1.2; per-name targeted queries deferred).

- [ ] **Step 4: Commit**

```bash
git add docs/progress/scout-primary-tracing-recall.md docs/GAPS.md
git commit -m "docs(scout): progress note + close G1.4 for primary-tracing recall"
```

- [ ] **Step 5: Live re-verify (owner-run, optional here)**

Re-run live Stage 1 once on a real trading day:
`PYTHONPATH=. .venv/Scripts/python.exe -m marketwind.scheduling --floor-only`
Expected: `primary≥1` when the day has real constituent disclosures. If still 0, escalate to per-name targeted queries (recorded non-goal) — do not loosen the floor silently.

---

## Notes for the executor

- **RED discipline (Iron Law):** every behavioral test must fail on an **assertion** for the right reason, never a bare ImportError/collection error. Task 3 Step 2 calls out the stub-then-assert dance explicitly; apply the same judgment elsewhere.
- **Surgical:** touch only the lines each task names. Do not "improve" adjacent gather/clean code.
- **The live akshare/fetch paths stay `# pragma: no cover`** — they are smoke-validated by Stage 1, not unit tests.
