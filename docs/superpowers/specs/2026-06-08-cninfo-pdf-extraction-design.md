# cninfo PDF-extraction limb — design

> **Read when:** picking up the cninfo PDF limb (the live-floor unblocker), or before wiring the live `enrich_primary_live` fetch path.

**Status:** approved (brainstorm 2026-06-08). Follows `primary-tracing` (branch `primary-tracing-cninfo`).

## Problem

`enrich_primary` routes a quantitative quote to its cninfo primary disclosure, fetches that disclosure, and attaches the URL **only if the quote's number appears in the fetched text** (the match-guard, Iron Law 3). Live, the `fetch` seam returns the cninfo `公告链接` **detail page** — a JS shell whose real announcement (the 业绩预告/快报 figures) lives in a separate PDF at `static.cninfo.com.cn/...PDF`. So `amount_matches` never sees the number, the guard correctly declines, and the live `primary≥1` floor stays blocked. The chain fails **closed** (never launders) but also never clears.

This limb makes the cninfo `fetch` seam return the **disclosure PDF's text** instead of the HTML shell, so the guard can confirm the figure and attach.

## Research grounding (real historical cninfo data, 2026-06-08)

- **PDF URL is derivable from the akshare record — no extra API call.** The `公告链接` carries `announcementId` + `announcementTime`; the PDF is the deterministic `http://static.cninfo.com.cn/finalpage/{announcementTime}/{announcementId}.PDF`. Verified: returns `200 application/pdf`.
- **A-share target disclosures extract cleanly.** 寒武纪 (688256) 2023 业绩快报 → `pypdf` extracted full text incl. `营业总收入 709,386,584.26`, `15.09%`; the existing `amount.py` regex pulled clean hits (`70,938.66 万元`, …).
- **H-share/港股 PDFs extract as mojibake** (non-standard CJK font, no ToUnicode). Digits survive but unit chars (万元/亿元) garble → `parse_amount` finds no amount → **no match → no attach** (fails closed — safe).
- **`pypdf` suffices** (pure-Python, light). No `pdfplumber`/`PyMuPDF`/OCR.

## Scope decisions (locked this brainstorm)

- **Q1 = A:** text-layer extraction only. **No OCR.** Image-only / scanned PDFs yield empty text → fail closed. (OCR'ing financial digits is a Law-3 corruption risk we will not add speculatively.)
- **Q2 = A:** derive the PDF URL from the detail-URL params (above). The `hisAnnouncement/query` API (returns `adjunctUrl`) is **not** used — deriving from the record we already have is simpler and reliable.
- **Scope = A:** ship the plain text-extract limb. Mojibake H-share PDFs and image PDFs degrade to no-attach and are **recorded gaps**, not handled this phase (a redundant mojibake guard would only re-do what the missing-unit match already does).

## Architecture

New module `marketwind/scout/cninfo_pdf.py`. The `fetch` seam stays `FetchFn = (url) -> Awaitable[str]`; only its live implementation changes. **`enrich_primary` and all its offline tests are untouched** — they search whatever string `fetch` returns.

### Units

| Unit | Kind | Responsibility |
|---|---|---|
| `derive_pdf_url(detail_url) -> str \| None` | pure | parse `announcementId`+`announcementTime` from a cninfo detail URL → `static.cninfo.com.cn/finalpage/{time}/{id}.PDF`; `None` if either param missing or non-cninfo URL |
| `extract_pdf_text(pdf_bytes) -> str` | pypdf | concatenate page text; any error/empty → `""` |
| `fetch_cninfo_disclosure(client, detail_url) -> str` | live glue (`# pragma: no cover`) | `derive_pdf_url` → `client.get` → verify `200` + `application/pdf` → `extract_pdf_text`; any failure → `""` |

### Data flow (cninfo path)

quote → `extract_claim` → route cninfo → `trace_to_primary` returns detail `公告链接` → **`fetch` (= `fetch_cninfo_disclosure`)** → derive PDF URL → httpx GET bytes → `extract_pdf_text` → `amount_matches(quote, pdf_text)` → attach iff the number matches.

### Live wiring change

In `enrich_primary_live`, the `fetch` seam is the only consumer of a fetched URL and it is always a cninfo disclosure (cninfo is the only routed venue). Replace the Playwright `_fetch` with an `httpx.AsyncClient`-based `fetch_cninfo_disclosure`, and **drop the Playwright browser launch from `enrich_primary_live`** (the disclosure fetch is now plain HTTP). Playwright stays in `gather_live` (untouched).

### Dependency

Add **`pypdf`** to project deps. `httpx` is already a dependency.

## Error handling & invariants

- Every limb degrades to `""`/`None` → no attach. **Fails closed; never launders** (Law 3).
- The **match-guard remains the sole arbiter**: `extract_claim`/routing only choose *where* to look; the number is always verified against the fetched PDF text.
- Mojibake / image PDFs → no parseable unit → no match → no attach.

## Testing (TDD, all offline)

- `derive_pdf_url`: valid detail URL → exact static URL; missing `announcementId` → `None`; missing `announcementTime` → `None`; non-cninfo URL → `None`.
- `extract_pdf_text`: tiny committed **ASCII fixture PDF** (handcrafted, core Helvetica font, contains a known token e.g. `MarketWind 123.45`) → returns that text; **corrupt bytes** → `""`. (Real CJK extraction is a *live* property — proven by the research probe + owner smoke, not unit-tested; embedding a CJK font in a fixture is brittle.)
- `fetch_cninfo_disclosure`: injected fake async client returning fixture PDF bytes → returns extracted text; non-200 → `""`; `derive_pdf_url` None → `""` with **no** GET issued.
- **E2E (extend `tests/scout/test_e2e_floor.py` style):** a quote whose number matches the fixture-PDF text attaches through `enrich_primary`→`evaluate_floor`; wrong number does not.

## Acceptance

- Offline suite green (new unit + e2e tests).
- Owner-only live smoke: against a real historical session/window, `enrich_primary_live` attaches ≥1 number-verified cninfo primary sourced from a real disclosure PDF, and the grounded floor can clear.

## Recorded gaps (carry forward)

- **Mojibake H-share / 港股 PDFs** — lower recall, fails closed (new).
- **Image-only / scanned PDFs** — no OCR, fails closed (new).
- Existing single-candidate-trace, category-narrowing, and exchange/regulator-venue gaps unchanged.
