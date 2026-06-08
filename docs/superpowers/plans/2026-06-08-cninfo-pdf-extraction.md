# cninfo PDF-extraction Limb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cninfo `fetch` seam return the disclosure PDF's extracted text (with the figures) instead of the JS-shell HTML, so the number-match guard can confirm and `enrich_primary` can attach a primary — unblocking the live `primary≥1` floor for A-share disclosures.

**Architecture:** A new `marketwind/scout/cninfo_pdf.py` with three units: `derive_pdf_url` (pure — build the `static.cninfo.com.cn/finalpage/{time}/{id}.PDF` URL from the akshare detail URL's query params), `extract_pdf_text` (pypdf — bytes → text, "" on any error), and `fetch_cninfo_disclosure` (live glue — derive→GET→verify→extract). The existing `FetchFn = (url)->Awaitable[str]` seam is unchanged; only the live `_fetch` in `enrich_primary_live` is rewired to call `fetch_cninfo_disclosure` over `httpx`, dropping Playwright from the enrich pass. Every limb fails closed (""/None → no attach), so the chain never launders (Iron Law 3).

**Tech Stack:** Python 3.11+, `pypdf` (new dep), `httpx` (already a dep), pytest (`asyncio_mode="auto"`). Run tests with `.venv/Scripts/python.exe -m pytest ...`.

**Spec:** `docs/superpowers/specs/2026-06-08-cninfo-pdf-extraction-design.md`.

**Context for the engineer (read once):**
- `marketwind/scout/enrich.py` — the pass that consumes `fetch`. Do NOT change `enrich_primary` itself; only `enrich_primary_live` (Task 4).
- `marketwind/scout/amount.py::amount_matches(quote_text, disclosure_text, *, rel_tol=0.02)` — the guard. Requires a digit adjacent to a unit token (`万亿|亿元|万元|亿|万|元` or `%|％|个百分点`).
- A real akshare detail URL looks like:
  `http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981&announcementId=1219447112&orgId=gshk0000981&announcementTime=2024-03-29`
  and the derived PDF URL (verified live, returns `200 application/pdf`) is:
  `http://static.cninfo.com.cn/finalpage/2024-03-29/1219447112.PDF`

---

### Task 1: `derive_pdf_url` + new module + pypdf dependency

**Files:**
- Modify: `pyproject.toml:6-19` (add `pypdf` to `dependencies`)
- Create: `marketwind/scout/cninfo_pdf.py`
- Create: `tests/scout/test_cninfo_pdf.py`

- [ ] **Step 1: Add the pypdf dependency**

In `pyproject.toml`, add `"pypdf>=6.0",` to the `dependencies` list (after `"playwright>=1.49",`). Then install it:

```bash
.venv/Scripts/python.exe -m pip install "pypdf>=6.0"
```

- [ ] **Step 2: Write the failing tests for `derive_pdf_url`**

Create `tests/scout/test_cninfo_pdf.py`:

```python
from marketwind.scout.cninfo_pdf import derive_pdf_url

_DETAIL = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&announcementId=1219447112&orgId=gshk0000981"
           "&announcementTime=2024-03-29")


def test_derive_pdf_url_builds_static_finalpage_url():
    assert derive_pdf_url(_DETAIL) == (
        "http://static.cninfo.com.cn/finalpage/2024-03-29/1219447112.PDF"
    )


def test_derive_pdf_url_missing_announcement_id_returns_none():
    url = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&orgId=gshk0000981&announcementTime=2024-03-29")
    assert derive_pdf_url(url) is None


def test_derive_pdf_url_missing_time_returns_none():
    url = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&announcementId=1219447112&orgId=gshk0000981")
    assert derive_pdf_url(url) is None


def test_derive_pdf_url_non_cninfo_url_returns_none():
    assert derive_pdf_url("https://news.example.com/article/123") is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -v`
Expected: FAIL — `ImportError: cannot import name 'derive_pdf_url'`. (This is a pure-function import; the assertion RED comes in Step 5 after the stub. Per CLAUDE.md §8, scaffold a wrong-sentinel stub next, then watch the assertion fail.)

- [ ] **Step 4: Scaffold a wrong-sentinel stub and watch the assertion fail**

Create `marketwind/scout/cninfo_pdf.py`:

```python
"""Fetch + text-extract a cninfo disclosure PDF so the number-match guard can
verify a quoted figure. Derive the static PDF URL from the akshare detail URL's
query params (no extra API call); extract text with pypdf; every limb fails
closed ("" / None → no attach), so the chain never launders (Iron Law 3)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def derive_pdf_url(detail_url: str) -> str | None:
    return ""  # wrong sentinel — Step 5 watches this fail
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py::test_derive_pdf_url_builds_static_finalpage_url -v`
Expected: FAIL — `assert '' == 'http://static.cninfo.com.cn/finalpage/2024-03-29/1219447112.PDF'` (a real assertion failure, not an import error).

- [ ] **Step 5: Implement `derive_pdf_url`**

Replace the body of `derive_pdf_url` in `marketwind/scout/cninfo_pdf.py`:

```python
def derive_pdf_url(detail_url: str) -> str | None:
    """Build the static cninfo PDF URL from a disclosure detail URL.

    Returns None if the URL lacks announcementId/announcementTime (non-cninfo
    or malformed) — caller degrades to no-attach.
    """
    qs = parse_qs(urlparse(detail_url).query)
    ann_id = qs.get("announcementId", [None])[0]
    ann_time = qs.get("announcementTime", [None])[0]
    if not ann_id or not ann_time:
        return None
    return f"http://static.cninfo.com.cn/finalpage/{ann_time}/{ann_id}.PDF"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml marketwind/scout/cninfo_pdf.py tests/scout/test_cninfo_pdf.py
git commit -m "feat(cninfo-pdf): derive static PDF URL from disclosure detail URL"
```

---

### Task 2: `extract_pdf_text` (pypdf → text, fail-closed)

**Files:**
- Modify: `marketwind/scout/cninfo_pdf.py`
- Modify: `tests/scout/test_cninfo_pdf.py`

- [ ] **Step 1: Add a minimal-PDF test helper and the failing tests**

Append to `tests/scout/test_cninfo_pdf.py`. The helper builds a correct one-page Helvetica PDF with a known ASCII text run (verified to extract cleanly with pypdf, no warnings). Chinese-font extraction is a live property proven by the owner smoke, not unit-tested.

```python
from marketwind.scout.cninfo_pdf import extract_pdf_text


def _build_minimal_pdf(text: str) -> bytes:
    """A correct one-page Helvetica PDF containing `text` (ASCII/latin-1)."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = b"BT /F1 18 Tf 20 100 Td (" + text.encode("latin-1") + b") Tj ET\n"
    objs.append(b"<</Length " + str(len(stream)).encode() + b">>stream\n"
                + stream + b"endstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj" + body + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += b"trailer<</Root 1 0 R/Size " + str(len(objs) + 1).encode() + b">>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return out


def test_extract_pdf_text_reads_text_layer():
    pdf = _build_minimal_pdf("MarketWind 123.45")
    assert "MarketWind 123.45" in extract_pdf_text(pdf)


def test_extract_pdf_text_corrupt_bytes_returns_empty():
    assert extract_pdf_text(b"not a pdf at all") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py::test_extract_pdf_text_reads_text_layer -v`
Expected: FAIL — `ImportError: cannot import name 'extract_pdf_text'`. Scaffold the wrong-sentinel stub next and watch the assertion fail.

- [ ] **Step 3: Scaffold a wrong-sentinel stub and watch the assertion fail**

Add the stub to `marketwind/scout/cninfo_pdf.py` (no new imports yet — they come in Step 4 with the real body, so the stub leaves no unused import):

```python
def extract_pdf_text(pdf_bytes: bytes) -> str:
    return "WRONG"  # wrong sentinel — watch the assertion fail
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py::test_extract_pdf_text_reads_text_layer -v`
Expected: FAIL — `assert 'MarketWind 123.45' in 'WRONG'` (real assertion failure).

- [ ] **Step 4: Implement `extract_pdf_text`**

Add these imports at the top of `marketwind/scout/cninfo_pdf.py` (after the existing `from urllib.parse import ...` line):

```python
import io

from pypdf import PdfReader
```

Then replace the stub body:

```python
def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Concatenate the text layer of every page. Returns "" on any pypdf error
    or when there is no extractable text (image-only / mojibake PDFs) — the
    caller then finds no number and declines to attach (fails closed)."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add marketwind/scout/cninfo_pdf.py tests/scout/test_cninfo_pdf.py
git commit -m "feat(cninfo-pdf): extract_pdf_text via pypdf, fail closed on error"
```

---

### Task 3: `fetch_cninfo_disclosure` (live glue: derive → GET → verify → extract)

**Files:**
- Modify: `marketwind/scout/cninfo_pdf.py`
- Modify: `tests/scout/test_cninfo_pdf.py`

Note: the real network GET is smoke-only, but the **glue logic** (derive None → no GET; non-200 → ""; wrong content-type → ""; happy path → extracted text) is unit-tested with an injected fake async client. So this function is NOT marked `# pragma: no cover`; it is covered by the tests below.

- [ ] **Step 1: Write the failing tests with an injected fake async client**

Append to `tests/scout/test_cninfo_pdf.py`:

```python
from marketwind.scout.cninfo_pdf import fetch_cninfo_disclosure

_DETAIL_OK = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688256"
              "&announcementId=1219210058&orgId=nssc1000595"
              "&announcementTime=2024-02-29")


class _FakeResp:
    def __init__(self, status_code, content, content_type="application/pdf"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


class _FakeClient:
    """Records GET calls and returns a queued response."""
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        return self._resp


async def test_fetch_disclosure_happy_path_returns_extracted_text():
    pdf = _build_minimal_pdf("net profit 12.34%")
    client = _FakeClient(_FakeResp(200, pdf))
    text = await fetch_cninfo_disclosure(client, _DETAIL_OK)
    assert "net profit 12.34%" in text
    assert client.calls == [
        "http://static.cninfo.com.cn/finalpage/2024-02-29/1219210058.PDF"
    ]


async def test_fetch_disclosure_non_200_returns_empty():
    client = _FakeClient(_FakeResp(404, b""))
    assert await fetch_cninfo_disclosure(client, _DETAIL_OK) == ""


async def test_fetch_disclosure_wrong_content_type_returns_empty():
    client = _FakeClient(_FakeResp(200, b"<html>shell</html>", "text/html"))
    assert await fetch_cninfo_disclosure(client, _DETAIL_OK) == ""


async def test_fetch_disclosure_underivable_url_skips_get():
    client = _FakeClient(_FakeResp(200, _build_minimal_pdf("x")))
    assert await fetch_cninfo_disclosure(client, "https://news.example.com/x") == ""
    assert client.calls == []  # no GET issued when URL is not derivable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -k fetch_disclosure -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_cninfo_disclosure'`. Scaffold the stub next, then watch an assertion fail.

- [ ] **Step 3: Scaffold a wrong-sentinel stub and watch the assertion fail**

Add to `marketwind/scout/cninfo_pdf.py`:

```python
async def fetch_cninfo_disclosure(client, detail_url: str) -> str:
    return "WRONG"  # wrong sentinel — watch the assertion fail
```

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py::test_fetch_disclosure_underivable_url_skips_get -v`
Expected: FAIL — `assert 'WRONG' == ''` (real assertion failure, not import error).

- [ ] **Step 4: Implement `fetch_cninfo_disclosure`**

Replace the stub in `marketwind/scout/cninfo_pdf.py`:

```python
async def fetch_cninfo_disclosure(client, detail_url: str) -> str:
    """Derive the PDF URL, download it, and return its extracted text.

    `client` is an httpx.AsyncClient-like object (awaitable .get returning a
    response with .status_code, .headers, .content). Any failure — underivable
    URL, non-200, non-PDF content-type, or extraction error — returns "" so the
    caller declines to attach (fails closed; never launders, Iron Law 3)."""
    pdf_url = derive_pdf_url(detail_url)
    if pdf_url is None:
        return ""
    resp = await client.get(pdf_url)
    if resp.status_code != 200:
        return ""
    if "application/pdf" not in resp.headers.get("content-type", ""):
        return ""
    return extract_pdf_text(resp.content)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -v`
Expected: PASS (10 passed).

- [ ] **Step 6: Commit**

```bash
git add marketwind/scout/cninfo_pdf.py tests/scout/test_cninfo_pdf.py
git commit -m "feat(cninfo-pdf): fetch_cninfo_disclosure glue (derive->GET->verify->extract)"
```

---

### Task 4: Integration test through `enrich_primary` + rewire `enrich_primary_live`

**Files:**
- Modify: `tests/scout/test_cninfo_pdf.py`
- Modify: `marketwind/scout/enrich.py:66-96` (`enrich_primary_live` only)

- [ ] **Step 1: Write the failing integration test (full new chain, offline)**

This drives a real quote through `enrich_primary` using `fetch_cninfo_disclosure` (via the fake client) as the `fetch` seam — exercising derive→extract→guard end to end. The quote's percent figure (`12.34%`) is ASCII-expressible in the fixture PDF, so the match is genuine. Append to `tests/scout/test_cninfo_pdf.py`:

```python
from datetime import date, datetime, timezone

from marketwind.scout.domain import Quote, Source
from marketwind.scout.enrich import enrich_primary

_CONS = {"中芯国际": "688981"}
_PUB = datetime(2024, 2, 29, tzinfo=timezone.utc)  # publish_ts is non-optional, tz-aware


def _quote(text):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=True)


def _source(quotes):
    return Source(url="https://news.example.com/a", domain="example.com",
                  publish_ts=_PUB, raw_content="x", quotes=quotes)


async def _classify_none(text):
    return None


async def test_integration_pdf_number_match_attaches_primary():
    pdf = _build_minimal_pdf("SMIC net profit margin 12.34%")
    client = _FakeClient(_FakeResp(200, pdf))

    async def trace(claim_type, symbol, on_date):
        assert (claim_type, symbol) == ("earnings", "688981")
        return _DETAIL_OK  # a cninfo detail URL → derivable PDF

    async def fetch(url):
        return await fetch_cninfo_disclosure(client, url)

    out = await enrich_primary(
        [_source([_quote("中芯国际净利润率同比12.34%")])],
        classify=_classify_none, trace=trace, fetch=fetch,
        constituents=_CONS, on_date=date(2024, 2, 29),
    )
    assert out[0].quotes[0].attached_primary_url == _DETAIL_OK


async def test_integration_pdf_wrong_number_does_not_attach():
    pdf = _build_minimal_pdf("SMIC net profit margin 99.99%")
    client = _FakeClient(_FakeResp(200, pdf))

    async def trace(claim_type, symbol, on_date):
        return _DETAIL_OK

    async def fetch(url):
        return await fetch_cninfo_disclosure(client, url)

    out = await enrich_primary(
        [_source([_quote("中芯国际净利润率同比12.34%")])],
        classify=_classify_none, trace=trace, fetch=fetch,
        constituents=_CONS, on_date=date(2024, 2, 29),
    )
    assert out[0].quotes[0].attached_primary_url is None
```

- [ ] **Step 2: Run the integration tests to verify they pass already**

These exercise only already-implemented code (Tasks 1-3 + existing `enrich_primary`), so they should PASS immediately — they lock the full chain against regression.

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_cninfo_pdf.py -k integration -v`
Expected: PASS (2 passed).

If either FAILS, stop and diagnose — the chain is wired wrong; do not proceed to the live rewire.

- [ ] **Step 3: Rewire `enrich_primary_live` to use httpx + the PDF limb (drop Playwright)**

Replace the entire `enrich_primary_live` function in `marketwind/scout/enrich.py` (lines 66-96) with:

```python
async def enrich_primary_live(conn, sources, *, on_date):  # pragma: no cover - live
    """Wire the real cninfo trace + disclosure-PDF fetch + live STAR50
    constituent map. The DeepSeek fallback classifier is stubbed to None this
    phase (rules-only live). The disclosure fetch is plain HTTP (httpx) →
    derive PDF URL → download → pypdf extract; no Playwright in the enrich pass
    (gather_live still uses Playwright separately). Smoke-only."""
    import httpx

    from marketwind.scout.cninfo_pdf import fetch_cninfo_disclosure
    from marketwind.scout.market import fetch_star50_constituents
    from marketwind.scout.primary import trace_to_primary

    constituents = fetch_star50_constituents()

    async def _classify(text):
        return None  # DeepSeek fallback is a follow-up; rules-only live for now

    async def _trace(claim_type, symbol, d):
        return await trace_to_primary(claim_type, symbol, d)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        async def _fetch(url):
            return await fetch_cninfo_disclosure(client, url)

        return await enrich_primary(sources, classify=_classify, trace=_trace,
                                    fetch=_fetch, constituents=constituents,
                                    on_date=on_date)
```

- [ ] **Step 4: Verify the offline enrich + cninfo-pdf suites still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/scout/test_enrich.py tests/scout/test_cninfo_pdf.py -v`
Expected: PASS (existing enrich tests + 12 cninfo-pdf tests). `enrich_primary` is untouched, so `test_enrich.py` must be unchanged-green.

- [ ] **Step 5: Run the full offline scout suite to confirm no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/scout -v`
Expected: PASS (all; `test_repo.py` is the only DB-dependent file — if it errors on a missing Postgres, that is pre-existing and unrelated; note it but do not treat it as a regression).

- [ ] **Step 6: Commit**

```bash
git add tests/scout/test_cninfo_pdf.py marketwind/scout/enrich.py
git commit -m "feat(cninfo-pdf): integrate PDF limb into enrich_primary_live (httpx, no Playwright)"
```

---

### Task 5: Progress note + recorded gaps

**Files:**
- Modify: `docs/progress/primary-tracing.md`

- [ ] **Step 1: Append the PDF-limb resolution to the progress note**

In `docs/progress/primary-tracing.md`, under the "Live-smoke findings (2026-06-08)" section, update finding **3** (the PDF blocker) to mark it RESOLVED, and add the new recorded gaps. Add this block after the existing finding-3 paragraph:

```markdown
**3 — RESOLVED (cninfo-pdf-extraction phase, 2026-06-08).** The fetch limb now
reads the disclosure PDF, not the JS shell. `marketwind/scout/cninfo_pdf.py`:
`derive_pdf_url` builds the static URL
`static.cninfo.com.cn/finalpage/{announcementTime}/{announcementId}.PDF` from
the akshare detail-record query params (no extra API call); `extract_pdf_text`
(pypdf) reads the text layer; `fetch_cninfo_disclosure` does derive→GET→verify
content-type→extract. `enrich_primary_live` now fetches over httpx (Playwright
dropped from the enrich pass). Research-verified live: A-share 业绩快报/预告 PDFs
(e.g. 寒武纪 688256) extract clean and the existing `amount_matches` guard
confirms the figure. The chain still fails **closed** on every error.
```

And add these bullets to the "Open gaps (recorded)" list:

```markdown
- **Mojibake H-share / 港股 disclosure PDFs** — some dual-listing PDFs use a
  non-standard CJK font with no ToUnicode map; `pypdf` returns garbled text, so
  the unit token never parses and the guard declines (fails closed, lower
  recall). No OCR by design (OCR'ing financial digits is a Law-3 risk).
- **Image-only / scanned disclosure PDFs** — no text layer → empty extract →
  no attach (fails closed). Out of scope (no OCR).
```

- [ ] **Step 2: Commit**

```bash
git add docs/progress/primary-tracing.md
git commit -m "docs(cninfo-pdf): record PDF limb resolved + mojibake/image gaps"
```

---

## Final verification (after all tasks)

- [ ] **Run the full offline suite** (subagent, per CLAUDE.md "test the entire pipeline"):

Run: `.venv/Scripts/python.exe -m pytest tests -v --ignore=tests/storage/test_repo.py`
Expected: all pass (test_repo.py needs Postgres; exclude it offline).

- [ ] **Owner-only live smoke (acceptance — needs network + docker):** run the existing live primary smoke against a real *historical* session/window and confirm `enrich_primary_live` attaches ≥1 number-verified cninfo primary sourced from a real disclosure PDF, and that the floor can clear:

```bash
PYTHONPATH=. .venv/Scripts/python.exe scripts/smoke_primary.py
```

Expected: at least one `[domain] '…' -> http://www.cninfo.com.cn/...` attach line and `PRIMARY-TRACING PROVEN`. (Under the simulated clock the *current* session has no real disclosures; point the smoke at a real historical window per the recorded limitation in `docs/progress/primary-tracing.md`.)
