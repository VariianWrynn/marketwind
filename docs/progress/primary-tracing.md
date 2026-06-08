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
| `scout/enrich.py::enrich_primary_live` | smoke-only wiring (rules-only classify, cninfo trace, httpx disclosure-PDF fetch — no Playwright) |
| `scout/cninfo_pdf.py` | derive static PDF URL + pypdf text-extract + fetch_cninfo_disclosure glue (fails closed) |
| `scout/market.py::fetch_star50_constituents` | smoke-only live constituent map |

## Invariants proved
- **Match-guard bites:** a same-topic disclosure with a different figure does NOT attach (`test_wrong_number_does_not_match`, `test_wrong_number_does_not_attach`).
- **No-attach-on-doubt:** trace-None / fetch-failure / number-mismatch / non-cninfo venue all degrade to `attached_primary_url=None`.
- **One bad quote never aborts the pass.**
- **Law 4 safe:** the classifier only routes (claim_type/company); the number is always verified against the fetched disclosure.

## Live-smoke findings (2026-06-08)

First real `gather_live → enrich_primary_live → evaluate_floor` smoke against the prev session (2026-06-05). Gather was healthy (12 sources, 267 quotes, **77 quantitative**, 9 outlets) but **0 primaries attached**. Diagnosis (`scripts/diag_primary.py`, gitignored) found two things:

1. **Pool composition, not a bug.** Every quantitative quote was index/sector *recap* ("科创50指数跌4.01%", "沪指报4027.74点", price-tickers like "中际旭创(1154.99…)跌超7%") — market price-action, not company disclosures (净利/营收/募资/减持). `extract_claim` resolved 0/78: a price-ticker mention of a constituent is **correctly** not an earnings claim, so nothing was cninfo-eligible. The chain ran clean and the floor stayed `False` (no laundering).
2. **Live trace limb was broken (now fixed).** `trace_to_primary` called `ak.stock_notice_report(symbol=code)`, but that API's `symbol` is a *report-type category* (`{"全部","财务报告","融资公告",…}`), not a stock code — so it `KeyError`-ed on every constituent. The P1a smoke had masked this by catching the exception as "expected for smoke," so the limb had never actually traced. **Fix:** switched to `ak.stock_zh_a_disclosure_report_cninfo(symbol=code, market="沪深京", start_date, end_date)` — the 巨潮 per-stock disclosure query; URL is the `公告链接` column. Verified live: returns real cninfo disclosures with URLs.

3. **Fetch limb can't read cninfo disclosure numbers (new blocker, follow-up).** A cninfo `公告链接` detail page is a JS shell whose actual announcement (the 业绩预告 net-profit/revenue figure) is a **PDF** loaded via `static.cninfo.com.cn/...PDF`. The existing Playwright `fetch_html` returns ~82 KB of page chrome but *not* the disclosure's numbers (probe of 688981's 2024-02-07 preview found only stray page-furniture percents). So `amount_matches` cannot confirm a cninfo figure and the guard **correctly declines to attach** (no-attach-on-doubt — safe, never launders), but the **live floor stays blocked** until the disclosure PDF is fetched + parsed. PDF fetch/parse for cninfo disclosures is a recorded follow-up; it is the next limb after the trace-API fix.

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

**Recorded limitation — simulated clock.** The project's "today" is 2026-06-08 but akshare returns *real* market data, so a date window anchored on a 2026 session has no real disclosures. A fully real one-shot "this session's pool clears the floor" therefore can't be demonstrated under the fake clock; the live trace limb is instead proven against a real *historical* window (verified: 688981/688256/688012 earnings → real cninfo detail URLs). Real-time operation will not have this constraint.

**Net live state (updated 2026-06-08, cninfo-pdf-extraction):** trace limb fixed and proven (real URLs); the fetch/number-verify limb now reads the disclosure **PDF** (`scout/cninfo_pdf.py`), so A-share figures can be confirmed live and the floor can clear when the pool carries a real disclosure quote. The full mechanism (extract→route→trace→fetch-PDF→number-verify→attach) is offline+E2E proven. Mojibake H-share and image-only PDFs degrade to no-attach (recorded gaps). Still fails **closed**, never laundering.

## Open gaps (recorded)
- **Exchange + regulator venue lookups + their match-guards** — continues P1a's "full venue mapping table is P2". `shareholding_reduction` (exchange, quantitative) needs this; `policy` (regulator) is qualitative.
- **DeepSeek fallback classifier is wired offline (seam tested) but stubbed to None in `enrich_primary_live`** — rules-only end-to-end live for now. Wiring the real DeepSeek call + its prompt-regression is a follow-up.
- **The Verifier / I3 check that consumes `attached_primary_url`** is the separate (P1b-deferred) Verifier phase — this phase produces the data, not the check.
- `fetch_star50_constituents` / `trace_to_primary` live akshare calls are smoke-validated only (the network call is `# pragma: no cover`; the URL-selection + category-mapping logic is unit-tested).
- **cninfo disclosure PDF parsing — RESOLVED (cninfo-pdf-extraction phase, 2026-06-08).** The `公告链接` PDF-backed JS shell is no longer fetched; `marketwind/scout/cninfo_pdf.py` derives + downloads + pypdf-extracts the disclosure PDF so the number-match guard can confirm A-share figures live. See finding 3 above. Two new fail-closed gaps below.
- **Mojibake H-share / 港股 disclosure PDFs** — some dual-listing PDFs use a
  non-standard CJK font with no ToUnicode map; `pypdf` returns garbled text, so
  the unit token never parses and the guard declines (fails closed, lower
  recall). No OCR by design (OCR'ing financial digits is a Law-3 risk).
- **Image-only / scanned disclosure PDFs** — no text layer → empty extract →
  no attach (fails closed). Out of scope (no OCR).
- **Single-candidate trace + category narrowing:** `trace_to_primary` returns one URL (the first disclosure in the window, narrowed by a `claim_type→cninfo category` map) and the number-match guard confirms it. A media figure whose disclosure is not the top hit in its category will miss; multi-candidate trace (try each until the number matches) is a follow-up. The guard keeps a miss *safe* (no attach), only lower-recall.

## How to test
`.venv/Scripts/python.exe -m pytest tests/scout/test_amount.py tests/scout/test_claim_extract.py tests/scout/test_enrich.py -v` — all offline.
Live smoke (owner-only): run the manual entrypoint against a real prior session and confirm the floor can clear with ≥1 cninfo-traced primary.
