# Scout gather fetch-cost fix + first live floor pass

> **Read when:** the live `--floor-only` run is slow / pins the machine, you're tuning gather fetch volume (`fetch.py`, `gather.py`, `outlets.py`), or you want the evidence that the grounded floor clears on a live pool (G0.3).

**Status:** complete + live-verified, 2026-06-16. Commit: `35d580a`. No separate spec — a surgical fix off the `scout-pername-gather` phase, decided inline with the owner.

**Why:** the first live `python -m marketwind.scheduling --floor-only` after the per-name gather shipped **crushed the laptop** and ran ~1 hr. A throwaway raw-fetch probe (deleted after) root-caused it: not bad resources, but **fan-out × per-page cost**. The per-name gather raised the query count 3→53, fanning out to **~443 unique URLs fetched sequentially through headless Chromium** (~63 min extrapolated), and many pages burned the full 15 s `networkidle` wait because ad/ticker pages never idle.

## What was done (B + A + C; D deferred)

| Knob | Change | Module | Effect |
|---|---|---|---|
| **B** | post-load idle wait `15 s → 3 s` (`_IDLE_WAIT_MS`, separate from the 15 s nav ceiling `_CEILING_MS`) | `scout/fetch.py` | kills the per-page stall on non-idle pages |
| **A** | cap each query to its **top-3** hits before fetch (`_PER_QUERY_CAP = 3`); Bocha ranks by relevance so the tail is noise | `scout/gather.py` `build_pool` | ~443 → ~120 page-loads |
| **C** | skip price/quote-table hosts before the fetch (`is_quote_aggregator`: `quote.eastmoney.com`, `q.stock.sohu.com`) | `scout/outlets.py` + `build_pool` | drops guaranteed-0-quote fetches |
| **D** | bounded-concurrency fetch (`asyncio.Semaphore` pool) **deferred to the cloud node** | — | recorded as **GAPS G4.5** (raises laptop peak load; recall-neutral) |

## Live verification — the milestone (G0.3 cleared)

Re-ran Stage 1 against Docker Postgres on 2026-06-16 (prev session 2026-06-15):

```
grounded=397   primary=1   outlets=15   passed=True   (exit 0)
runtime 19:36:11 → 19:39:31  ≈ 3 min 20 s
```

- **`primary` cleared 0 for the first time** → the floor `8/1/2` passes. A constituent disclosure surfaced via the per-name queries, a quote span carried name + keyword + number, traced to a number-verified cninfo primary, and the `amount_matches` guard confirmed it (Iron Law 3 intact).
- **Runtime ~3 min, no machine crush** → the B+A+C cost fix is validated live (was ~63 min).

This answers the go-live's riskiest unknown (G0.3: "if the floor never clears, the report never publishes").

## Key invariants proved here

- **Recall-neutral cost cut.** A/C only drop the long tail and price-table pages — index price-page numbers never trace to a *constituent* cninfo primary, so the primary goal is untouched. The live `primary=1` confirms the on-topic disclosures still land.
- **Assertion-level RED for every testable change.** `is_quote_aggregator` (`assert False is True` → fixed), `build_pool` cap (`assert len(fetched)==5` → `==3`), `build_pool` skip (`assert junk not in [good, junk]`). B is a constant inside the live-only `fetch_html` (`# pragma: no cover`) — no offline browser assertion possible; pure-logic fetch tests stay green.
- **Fail-closed preserved.** The dedup / fetch-skip / empty-quotes-skip loop is otherwise unchanged; junk pages that slip the host-list still die at `amount_matches`.

## How to test

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q \
  tests/scout/test_outlets.py tests/scout/test_fetch.py \
  tests/scheduling/test_gather.py tests/scout/test_query.py   # 23 tests
```

Live floor probe (owner-run, needs Docker Postgres up): `python -m marketwind.scheduling --floor-only`.

## Out of scope / still open

- **D (bounded concurrency)** → GAPS G4.5, cloud node only.
- **Skip-list is intentionally minimal** — only the two evidence-proven hosts; extend `_QUOTE_AGGREGATOR_HOSTS` if a future run shows other quote hosts wasting fetches.
- **Single-run proof.** The floor cleared on one live run (2026-06-15 data); search results vary day to day, so a quiet-calendar day may still read `primary=0` (a disclosure-availability reality, not a regression).
