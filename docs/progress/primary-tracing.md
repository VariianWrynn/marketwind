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
