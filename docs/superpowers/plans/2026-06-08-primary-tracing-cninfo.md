# Primary-tracing Enrichment (cninfo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-gather `enrich_primary` pass that resolves and attaches a *number-verified* cninfo primary-disclosure URL to each quantitative quote, so the grounded floor can pass on real data without laundering a wrong match.

**Architecture:** Three new pure, offline-testable units — `amount.py` (parse + tolerant numeric match), `claim_extract.py` (rules classifier), `enrich.py` (the async pass over injected seams) — plus `# pragma: no cover` live wiring (`enrich_primary_live`, a constituent fetcher, and a 2-line `__main__` integration). `build_pool` is untouched. The pass attaches a primary URL only when a fetched disclosure contains the quote's figure within tolerance; every other path leaves `attached_primary_url=None` (honest shortfall).

**Tech Stack:** Python 3.11+, pytest (asyncio_mode=auto), dataclasses, akshare + Playwright + asyncpg (live only). Run tests with `.venv/Scripts/python.exe`.

**Design spec:** `docs/superpowers/specs/2026-06-08-primary-tracing-enrichment-design.md`

**Invariants this plan must preserve (from CLAUDE.md / CITATION_CONTRACT):**
- **Iron Law 3** — a quantitative claim's primary must actually support the number. The match-guard is the defense; a deliberate wrong-number test MUST prove it bites.
- **Iron Law 4** — the model (DeepSeek fallback) only picks *where to look* (claim_type/company), never *what's true*. Never attach on the model's say-so; always number-verify against the fetched disclosure.
- **Attach-only-on-confirmation / no-attach-on-doubt** — any seam failure degrades to no-attach; one bad quote never aborts the pass.
- **TDD RED gate** — every behavioral test must fail on an *assertion* (or domain error) for the expected reason before implementation. A bare ImportError is only a valid RED for a pure construction/smoke-import test.
- **Surgical** — `build_pool`, `numbers.py`, `domain.py` `Quote`/`Source`, and the offline `run_once` tests are NOT modified.

**File structure (locked here):**
| File | Responsibility |
|---|---|
| `marketwind/scout/amount.py` (new) | `NormalizedAmount`, `parse_amount`, `amount_matches` — money/percent value extraction + tolerant comparison |
| `marketwind/scout/claim_extract.py` (new) | `ClaimRef`, `extract_claim` — rules classifier (closed-set company + keyword claim_type) |
| `marketwind/scout/enrich.py` (new) | `enrich_primary` (pure async pass) + `enrich_primary_live` (`# pragma: no cover`) |
| `marketwind/scout/market.py` (modify) | add `fetch_star50_constituents` (`# pragma: no cover` live) |
| `marketwind/scheduling/__main__.py` (modify) | wrap `_gather` to enrich the live pool before the floor |
| `docs/progress/primary-tracing.md` (new) | progress note + recorded gaps |
| `tests/scout/test_amount.py`, `test_claim_extract.py`, `test_enrich.py` (new) | offline unit tests |

---

### Task 1: Amount parser + tolerant matcher (`amount.py`)

**Files:**
- Create: `marketwind/scout/amount.py`
- Test: `tests/scout/test_amount.py`

`numbers.py` only *detects* a quantity (`is_quantitative` → bool); it does not extract a value. This unit extracts canonical numeric values (money in base 元, and percentages) and compares a quote's figures against a disclosure's within relative tolerance — so 媒体 "3.6亿" matches a filing's "360,000,000元" but NOT "5亿".

- [ ] **Step 1: Write the failing tests**

```python
# tests/scout/test_amount.py
from marketwind.scout.amount import NormalizedAmount, parse_amount, amount_matches


def test_parse_money_magnitudes():
    assert NormalizedAmount("value", 3.6e8) in parse_amount("净利润3.6亿")
    assert NormalizedAmount("value", 3.6e8) in parse_amount("利润3.60亿元")
    assert NormalizedAmount("value", 3.6e8) in parse_amount("利润360,000,000元")
    assert NormalizedAmount("value", 1.2e12) in parse_amount("规模1.2万亿")
    assert NormalizedAmount("value", 5.0e4) in parse_amount("募资5万元")


def test_parse_percent():
    assert NormalizedAmount("percent", 7.0) in parse_amount("持股7.00%")
    assert NormalizedAmount("percent", 0.9) in parse_amount("下降0.9个百分点")


def test_match_across_unit_divergence():
    assert amount_matches("净利3.6亿", "本期净利润为360,000,000元") is True


def test_match_within_rounding_tolerance():
    # 3.6亿 vs 3.58亿 — within 2% default tolerance
    assert amount_matches("净利3.6亿", "净利润3.58亿元") is True


def test_wrong_number_does_not_match():
    # THE GUARD: a same-topic disclosure with a different figure must NOT match
    assert amount_matches("净利3.6亿", "净利润5亿元") is False


def test_no_parseable_amount_does_not_match():
    assert amount_matches("公司发布公告", "本期净利润为360,000,000元") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_amount.py -v`
Expected: FAIL — collection succeeds only after the stub in Step 3; first run errors on missing module. To get an assertion-level RED, create the stub in Step 3a FIRST, then watch the assertions fail.

- [ ] **Step 3a: Scaffold a wrong-sentinel stub so tests run (for a true assertion RED)**

```python
# marketwind/scout/amount.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedAmount:
    kind: str  # "value" | "percent"
    value: float


def parse_amount(text: str) -> list[NormalizedAmount]:
    return []  # wrong sentinel — tests assert specific amounts


def amount_matches(quote_text: str, disclosure_text: str, *, rel_tol: float = 0.02) -> bool:
    return True  # wrong sentinel — guard test expects False
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_amount.py -v`
Expected: FAIL — `test_parse_money_magnitudes` fails on `in []`; `test_wrong_number_does_not_match` fails because `True is not False`. These are assertion failures for the right reason (RED).

- [ ] **Step 3b: Write the real implementation**

```python
# marketwind/scout/amount.py
"""Extract canonical money/percent values from Chinese financial text and
compare a quote's figures against a disclosure's within relative tolerance.

numbers.py only DETECTS a quantity; this module EXTRACTS the value, so the
primary-tracing match-guard can confirm a disclosure actually carries the
quote's number (defends Iron Law 3). Money is normalized to base 元; share
counts (股/手) are intentionally NOT parsed — those are exchange-venue claims,
out of scope for the cninfo path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# number (commas/decimals) + a money magnitude. Longest tokens first so 万亿 /
# 亿元 / 万元 win over 亿 / 万 / 元.
_AMOUNT = re.compile(r"(\d[\d,]*\.?\d*)\s*(万亿|亿元|万元|亿|万|元)")
_PERCENT = re.compile(r"(\d[\d,]*\.?\d*)\s*(%|％|个百分点)")
_MULT = {"万亿": 1e12, "亿元": 1e8, "万元": 1e4, "亿": 1e8, "万": 1e4, "元": 1.0}


@dataclass(frozen=True)
class NormalizedAmount:
    kind: str  # "value" | "percent"
    value: float


def parse_amount(text: str) -> list[NormalizedAmount]:
    out: list[NormalizedAmount] = []
    for m in _AMOUNT.finditer(text):
        num = float(m.group(1).replace(",", ""))
        out.append(NormalizedAmount("value", num * _MULT[m.group(2)]))
    for m in _PERCENT.finditer(text):
        num = float(m.group(1).replace(",", ""))
        out.append(NormalizedAmount("percent", num))
    return out


def _close(a: float, b: float, rel_tol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def amount_matches(quote_text: str, disclosure_text: str, *, rel_tol: float = 0.02) -> bool:
    """True iff some money/percent figure in the quote appears in the disclosure
    within rel_tol (handling unit/rounding divergence). Same kind must match
    same kind (a value never matches a percent)."""
    q_amounts = parse_amount(quote_text)
    d_amounts = parse_amount(disclosure_text)
    for qa in q_amounts:
        for da in d_amounts:
            if qa.kind == da.kind and _close(qa.value, da.value, rel_tol):
                return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_amount.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/amount.py tests/scout/test_amount.py
git commit -m "feat(primary-tracing): amount parser + tolerant number match-guard"
```

---

### Task 2: Rules claim classifier (`claim_extract.py`)

**Files:**
- Create: `marketwind/scout/claim_extract.py`
- Test: `tests/scout/test_claim_extract.py`

Extracts `(claim_type, symbol)` from a quote using a **closed-set** company match (constituent name → symbol, injected) and a keyword claim_type table. Returns None when either is missing — the caller then tries the DeepSeek fallback. Company is a closed set, so matching is exact substring, not fuzzy.

- [ ] **Step 1: Write the failing tests**

```python
# tests/scout/test_claim_extract.py
from marketwind.scout.claim_extract import ClaimRef, extract_claim

CONS = {"中芯国际": "688981", "澜起科技": "688008"}


def test_earnings_keyword_and_company():
    ref = extract_claim("中芯国际净利润3.6亿元", CONS)
    assert ref == ClaimRef(claim_type="earnings", symbol="688981")


def test_fundraising_keyword():
    assert extract_claim("澜起科技募资5亿元", CONS).claim_type == "fundraising"


def test_shareholding_reduction_keyword():
    assert extract_claim("中芯国际遭股东减持100万股", CONS).claim_type == "shareholding_reduction"


def test_no_known_company_returns_none():
    assert extract_claim("某未知公司净利润3.6亿元", CONS) is None


def test_no_claim_keyword_returns_none():
    assert extract_claim("中芯国际发布了一则公告", CONS) is None
```

- [ ] **Step 2: Scaffold a wrong-sentinel stub so tests run**

```python
# marketwind/scout/claim_extract.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimRef:
    claim_type: str
    symbol: str


def extract_claim(text: str, constituents: dict[str, str]) -> ClaimRef | None:
    return None  # wrong sentinel — happy-path tests expect a ClaimRef
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_claim_extract.py -v`
Expected: FAIL — `test_earnings_keyword_and_company` fails asserting `None == ClaimRef(...)`. Assertion-level RED for the right reason.

- [ ] **Step 3: Write the real implementation**

```python
# marketwind/scout/claim_extract.py
"""Rules-first claim classifier: map a quote to (claim_type, symbol) using a
closed-set constituent match + keyword table. Returns None when inconclusive
(caller falls back to the DeepSeek classifier). This only picks WHERE to look
for a primary — never asserts what is true (Iron Law 4 safe)."""
from __future__ import annotations

from dataclasses import dataclass

# Most specific first; first hit wins.
_CLAIM_KEYWORDS: list[tuple[str, str]] = [
    ("减持", "shareholding_reduction"),
    ("募资", "fundraising"),
    ("募集", "fundraising"),
    ("IPO", "fundraising"),
    ("净利", "earnings"),
    ("利润", "earnings"),
    ("营收", "earnings"),
    ("业绩", "earnings"),
    ("政策", "policy"),
    ("部委", "policy"),
]


@dataclass(frozen=True)
class ClaimRef:
    claim_type: str
    symbol: str


def _match_company(text: str, constituents: dict[str, str]) -> str | None:
    # Longest name first so a shorter name that is a prefix of another cannot
    # steal the match.
    for name in sorted(constituents, key=len, reverse=True):
        if name in text:
            return constituents[name]
    return None


def _match_claim_type(text: str) -> str | None:
    for keyword, claim_type in _CLAIM_KEYWORDS:
        if keyword in text:
            return claim_type
    return None


def extract_claim(text: str, constituents: dict[str, str]) -> ClaimRef | None:
    symbol = _match_company(text, constituents)
    claim_type = _match_claim_type(text)
    if symbol is None or claim_type is None:
        return None
    return ClaimRef(claim_type=claim_type, symbol=symbol)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_claim_extract.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/claim_extract.py tests/scout/test_claim_extract.py
git commit -m "feat(primary-tracing): rules claim classifier (closed-set company + keyword)"
```

---

### Task 3: The enrichment pass (`enrich.py::enrich_primary`)

**Files:**
- Create: `marketwind/scout/enrich.py`
- Test: `tests/scout/test_enrich.py`

The pure async pass. Walks only `is_quantitative` quotes; per quote: rules-extract → DeepSeek fallback if inconclusive → route (cninfo only) → trace → fetch → number-verify → attach. Every seam failure degrades to no-attach; one bad quote never aborts. `classify`, `trace`, `fetch` are injected async seams (so the pass is fully offline-testable). Rebuilds frozen `Quote`/`Source` via `dataclasses.replace` (no input mutation).

**Reference — existing types (do NOT modify):**
- `Quote(text, span_start, span_end, context_before, context_after, is_quantitative, quote_type="factual", attached_primary_url=None)` — frozen.
- `Source(url, domain, publish_ts, raw_content, byline=None, is_primary=False, quotes=[])` — not frozen.
- `marketwind.scout.primary.primary_venue_for(claim_type) -> str | None` — already returns "cninfo" for ipo/fundraising/earnings.

- [ ] **Step 1: Write the failing tests**

```python
# tests/scout/test_enrich.py
from dataclasses import replace
from datetime import datetime, timezone

from marketwind.scout.claim_extract import ClaimRef
from marketwind.scout.domain import Quote, Source
from marketwind.scout.enrich import enrich_primary

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)
CONS = {"中芯国际": "688981"}


def _q(text, quant=True):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=quant)


def _src(quotes):
    return Source(url="https://news.example.com/a", domain="example.com",
                  publish_ts=NOW, raw_content="x", quotes=quotes)


async def _classify_none(text):
    return None


async def _never_fetch(url):
    raise AssertionError("fetch must not be called")


async def _never_trace(ct, sym, on_date):
    raise AssertionError("trace must not be called")


async def test_confirmed_number_attaches_primary():
    async def trace(ct, sym, on_date):
        assert (ct, sym) == ("earnings", "688981")
        return "https://cninfo.com.cn/d1"

    async def fetch(url):
        return "本期净利润为360,000,000元"

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d1"


async def test_wrong_number_does_not_attach():
    async def trace(ct, sym, on_date):
        return "https://cninfo.com.cn/d1"

    async def fetch(url):
        return "本期净利润为5亿元"  # different figure

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_non_quantitative_quote_skipped():
    out = await enrich_primary([_src([_q("中芯国际发布公告", quant=False)])],
                               classify=_classify_none, trace=_never_trace,
                               fetch=_never_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_fetch_failure_degrades_to_no_attach():
    async def trace(ct, sym, on_date):
        return "https://cninfo.com.cn/d1"

    async def fetch(url):
        raise RuntimeError("network down")

    out = await enrich_primary([_src([_q("中芯国际净利润3.6亿元")])],
                               classify=_classify_none, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None


async def test_deepseek_fallback_used_when_rules_inconclusive():
    async def classify(text):
        return ClaimRef(claim_type="earnings", symbol="688981")

    async def trace(ct, sym, on_date):
        return "https://cninfo.com.cn/d1"

    async def fetch(url):
        return "净利润3.6亿元"

    # No known company in text → rules return None → fallback resolves it.
    out = await enrich_primary([_src([_q("某半导体大厂净利润3.6亿元")])],
                               classify=classify, trace=trace, fetch=fetch,
                               constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url == "https://cninfo.com.cn/d1"


async def test_one_bad_quote_does_not_abort_rest():
    async def trace(ct, sym, on_date):
        return "https://cninfo.com.cn/d1"

    async def fetch(url):
        return "净利润3.6亿元"

    good = _q("中芯国际净利润3.6亿元")
    bad = _q("中芯国际净利润3.6亿元")
    src = _src([bad, good])

    calls = {"n": 0}

    async def flaky_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "净利润3.6亿元"

    out = await enrich_primary([src], classify=_classify_none, trace=trace,
                               fetch=flaky_fetch, constituents=CONS, on_date=NOW.date())
    assert out[0].quotes[0].attached_primary_url is None        # first fetch failed
    assert out[0].quotes[1].attached_primary_url == "https://cninfo.com.cn/d1"
```

- [ ] **Step 2: Scaffold a wrong-sentinel stub so tests run**

```python
# marketwind/scout/enrich.py
from __future__ import annotations
from datetime import date


async def enrich_primary(sources, *, classify, trace, fetch, constituents,
                         on_date: date, rel_tol: float = 0.02):
    return sources  # wrong sentinel — confirmed-number test expects an attach
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_enrich.py -v`
Expected: FAIL — `test_confirmed_number_attaches_primary` fails asserting `None == "https://cninfo.com.cn/d1"`. Assertion-level RED for the right reason.

- [ ] **Step 3: Write the real implementation**

```python
# marketwind/scout/enrich.py
"""Post-gather primary-tracing pass (cninfo). For each quantitative quote:
rules-extract (claim_type, symbol) -> DeepSeek fallback if inconclusive ->
route (cninfo only) -> trace candidate disclosure -> fetch it -> confirm the
quote's number appears (match-guard) -> attach the URL. Any failure degrades
to no-attach (Iron Law 3: never attach a primary we did not number-verify).

classify/trace/fetch are injected async seams so the whole pass is offline-
testable; enrich_primary_live wires the real ones (smoke-only)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date

from marketwind.scout.amount import amount_matches
from marketwind.scout.claim_extract import ClaimRef, extract_claim
from marketwind.scout.domain import Quote, Source
from marketwind.scout.primary import primary_venue_for

ClassifyFn = Callable[[str], Awaitable[ClaimRef | None]]
TraceFn = Callable[[str, str, date], Awaitable[str | None]]
FetchFn = Callable[[str], Awaitable[str]]


async def _resolve(quote: Quote, *, classify: ClassifyFn, trace: TraceFn,
                   fetch: FetchFn, constituents: dict[str, str], on_date: date,
                   rel_tol: float) -> str | None:
    """Return a number-verified primary URL for this quote, or None."""
    if not quote.is_quantitative:
        return None
    ref = extract_claim(quote.text, constituents)
    if ref is None:
        ref = await classify(quote.text)
    if ref is None:
        return None
    if primary_venue_for(ref.claim_type) != "cninfo":
        return None  # exchange / regulator venues are out of scope (recorded gap)
    try:
        url = await trace(ref.claim_type, ref.symbol, on_date)
        if not url:
            return None
        disclosure = await fetch(url)
    except Exception:
        return None  # any live failure → no attach, never abort
    if not amount_matches(quote.text, disclosure, rel_tol=rel_tol):
        return None  # THE GUARD: disclosure must carry the quote's number
    return url


async def enrich_primary(sources: list[Source], *, classify: ClassifyFn,
                         trace: TraceFn, fetch: FetchFn,
                         constituents: dict[str, str], on_date: date,
                         rel_tol: float = 0.02) -> list[Source]:
    out: list[Source] = []
    for src in sources:
        new_quotes: list[Quote] = []
        for q in src.quotes:
            url = await _resolve(q, classify=classify, trace=trace, fetch=fetch,
                                 constituents=constituents, on_date=on_date,
                                 rel_tol=rel_tol)
            new_quotes.append(replace(q, attached_primary_url=url) if url else q)
        out.append(replace(src, quotes=new_quotes))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_enrich.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/enrich.py tests/scout/test_enrich.py
git commit -m "feat(primary-tracing): enrich_primary pass — extract/route/trace/number-verify/attach"
```

---

### Task 4: Live wiring (`enrich_primary_live`, constituent fetcher, `__main__`)

**Files:**
- Modify: `marketwind/scout/enrich.py` (append `enrich_primary_live`)
- Modify: `marketwind/scout/market.py` (append `fetch_star50_constituents`)
- Modify: `marketwind/scheduling/__main__.py:62-63` (wrap `_gather`)

This task is `# pragma: no cover` live wiring — no behavioral unit test (mirrors how `gather_live`/`main` shipped in P2a). Verification = the offline suite stays green AND the module imports without error. **Do NOT** invent a unit test that imports playwright/akshare/asyncpg.

- [ ] **Step 1: Append the live composition to `enrich.py`**

```python
# appended to marketwind/scout/enrich.py
async def enrich_primary_live(conn, sources: list[Source], *, on_date: date) -> list[Source]:  # pragma: no cover - live
    """Wire the real DeepSeek classifier + cninfo trace + Playwright fetch +
    live STAR50 constituent map. Smoke-only."""
    from playwright.async_api import async_playwright

    from marketwind.scout import fetch as fetch_mod
    from marketwind.scout.market import fetch_star50_constituents
    from marketwind.scout.primary import trace_to_primary

    constituents = fetch_star50_constituents()

    async def _classify(text: str) -> ClaimRef | None:
        return None  # DeepSeek fallback classifier is a follow-up; rules-only live for now

    async def _trace(claim_type: str, symbol: str, d: date) -> str | None:
        return await trace_to_primary(claim_type, symbol, d)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context()

        async def _fetch(url: str) -> str:
            return await fetch_mod.fetch_html(context, url)

        try:
            return await enrich_primary(sources, classify=_classify, trace=_trace,
                                        fetch=_fetch, constituents=constituents,
                                        on_date=on_date)
        finally:
            await browser.close()
```

Note: the DeepSeek fallback is stubbed to `None` in the live wiring for this phase (rules-only end-to-end). The seam exists and is exercised offline in Task 3; wiring the real DeepSeek call is a follow-up, recorded as a gap in Task 5. This keeps the live smoke deterministic and model-free.

- [ ] **Step 2: Append the constituent fetcher to `market.py`**

```python
# appended to marketwind/scout/market.py
def fetch_star50_constituents() -> dict[str, str]:  # pragma: no cover - live akshare
    """Return {constituent_name: symbol} for the STAR50 (科创50) index.

    akshare column names vary by version; adjust at smoke time if needed.
    """
    import akshare as ak

    df = ak.index_stock_cons(symbol="000688")
    return {str(r["品种名称"]): str(r["品种代码"]) for _, r in df.iterrows()}
```

- [ ] **Step 3: Wrap `_gather` in `__main__.py` to enrich before the floor**

In `marketwind/scheduling/__main__.py`, change the import block and `_gather` (currently lines 44-45 import and 62-63):

Add to the imports inside `main()` (next to `from marketwind.scout.gather import gather_live`):

```python
    from marketwind.scout.enrich import enrich_primary_live
```

Replace `_gather`:

```python
        async def _gather():
            pool = await gather_live(conn, now=now, prev_session=prev)
            return await enrich_primary_live(conn, pool, on_date=prev)
```

- [ ] **Step 4: Verify offline suite is green and the modules import**

Run: `.venv/Scripts/python.exe -m pytest tests/scout tests/scheduling -q`
Expected: PASS (all offline scout + scheduling tests; no new failures).

Run: `.venv/Scripts/python.exe -c "import marketwind.scout.enrich, marketwind.scout.market, marketwind.scheduling.__main__; print('imports ok')"`
Expected: prints `imports ok` (no ImportError).

- [ ] **Step 5: Commit**

```bash
git add marketwind/scout/enrich.py marketwind/scout/market.py marketwind/scheduling/__main__.py
git commit -m "feat(primary-tracing): live wiring — enrich_primary_live + constituent fetch + __main__ integration"
```

---

### Task 5: Progress note + recorded gaps

**Files:**
- Create: `docs/progress/primary-tracing.md`
- Modify: `docs/progress/P1a-scout.md` (update the cninoly gap line)
- Modify: `docs/progress/P2a-core-triggering.md` (mark the primary-tracing blocker addressed)

No code; documentation closing the loop. No RED/GREEN — verification is that the files read correctly.

- [ ] **Step 1: Write `docs/progress/primary-tracing.md`**

```markdown
# Primary-tracing (cninfo)

> **Read when:** picking up primary-tracing / the live floor, or before the Verifier phase (which consumes `attached_primary_url` for I3).

**Status:** complete. Branch `primary-tracing-cninfo`. Spec: `docs/superpowers/specs/2026-06-08-primary-tracing-enrichment-design.md`. Plan: `docs/superpowers/plans/2026-06-08-primary-tracing-cninfo.md`.

**What it delivers:** a post-gather `enrich_primary` pass that attaches a *number-verified* cninfo primary-disclosure URL to each quantitative quote, unblocking the P2a live-floor gap. `build_pool` is untouched.

## Modules
| Module | What it does |
|---|---|
| `scout/amount.py` | parse money/percent values + tolerant match (`amount_matches`) |
| `scout/claim_extract.py` | rules classifier: closed-set company + keyword claim_type |
| `scout/enrich.py::enrich_primary` | per-quant-quote extract→route→trace→number-verify→attach, injected seams |
| `scout/enrich.py::enrich_primary_live` | smoke-only wiring (rules-only classify, cninfo trace, Playwright fetch) |
| `scout/market.py::fetch_star50_constituents` | smoke-only live constituent map |

## Invariants proved
- **Match-guard bites:** a same-topic disclosure with a different figure does NOT attach (`test_wrong_number_does_not_match`, `test_wrong_number_does_not_attach`).
- **No-attach-on-doubt:** trace-None / fetch-failure / number-mismatch / non-cninfo venue all degrade to `attached_primary_url=None`.
- **One bad quote never aborts the pass.**
- **Law 4 safe:** the classifier only routes (claim_type/company); the number is always verified against the fetched disclosure.

## Open gaps (recorded)
- **Exchange + regulator venue lookups + their match-guards** — continues P1a's "full venue mapping table is P2". `shareholding_reduction` (exchange, quantitative) needs this; `policy` (regulator) is qualitative.
- **DeepSeek fallback classifier is wired offline (seam tested) but stubbed to None in `enrich_primary_live`** — rules-only end-to-end live for now. Wiring the real DeepSeek call + its prompt-regression is a follow-up.
- **The Verifier / I3 check that consumes `attached_primary_url`** is the separate (P1b-deferred) Verifier phase — this phase produces the data, not the check.
- `fetch_star50_constituents` / `trace_to_primary` akshare column + venue coverage are smoke-validated only.

## How to test
`.venv/Scripts/python.exe -m pytest tests/scout/test_amount.py tests/scout/test_claim_extract.py tests/scout/test_enrich.py -v` — all offline.
Live smoke (owner-only): run the manual entrypoint against a real prior session and confirm the floor can clear with ≥1 cninfo-traced primary.
```

- [ ] **Step 2: Update the P1a gap line**

In `docs/progress/P1a-scout.md`, change the line:
```
- Primary trace covers cninfo only; full venue mapping table is P2.
```
to:
```
- Primary trace covers cninfo only. The enrichment wiring + number match-guard landed in `docs/progress/primary-tracing.md`; exchange/regulator venue lookups remain deferred there.
```

- [ ] **Step 3: Update the P2a primary-tracing blocker note**

In `docs/progress/P2a-core-triggering.md`, in the "Open gaps" section, change the start of the **Primary-tracing wiring** bullet from:
```
- **Primary-tracing wiring (BLOCKER for live floor):** `build_pool` sets `attached_primary_url=None`; the live floor cannot pass until claim_type/company extraction + `trace_to_primary` are wired.
```
to:
```
- **Primary-tracing wiring (ADDRESSED — see `docs/progress/primary-tracing.md`):** the cninoly `enrich_primary` pass now attaches number-verified primaries after gather, so the live floor can clear. Exchange/regulator venues + the real DeepSeek fallback remain follow-ups there.
```

- [ ] **Step 4: Commit**

```bash
git add docs/progress/primary-tracing.md docs/progress/P1a-scout.md docs/progress/P2a-core-triggering.md
git commit -m "docs(primary-tracing): progress note + close P1a/P2a gap lines"
```

---

## Final verification (after all tasks)

Run the full offline scout + scheduling suites and confirm no regressions:

```bash
.venv/Scripts/python.exe -m pytest tests/scout tests/scheduling -q
```
Expected: all pass (Task 1–3 add 17 tests; pre-existing offline tests unchanged). Postgres-integration tests under `tests/scout/test_repo.py` stay environmental (need a running DB) and are unaffected.

Then dispatch a final reviewer over the whole branch, and an end-to-end integration check that a seeded cninfo-backed pool now clears the floor through `enrich_primary → evaluate_floor`.
