# Writer I3 publish-path — primaries survive to verification

> **Read when:** the live `--send-real` run fails Verifier check **I3** (Iron Law 3: no quantitative claim without a primary source), or working on the enrich→DB→Writer handoff (`scout/enrich.py`, `storage/repo.py`, `writer/runner.py`, `writer/select.py`).

**Status:** complete (offline + DB tests green), 2026-06-17. Two surgical, independently revertible changes. No spec/plan — these are targeted bug fixes found while driving the first real autonomous push, not a phase.

**Why:** after primary-tracing recall work landed (`scout-primary-tracing-recall.md`), the live floor cleared `primary≥1`, but `--send-real` still failed Verifier I3 with 7–10+ violations. Two root causes, in series along the publish path:

1. **Enriched primaries never reached the DB.** `enrich_primary_live` attached `attached_primary_url` to ~10 quotes **in memory** and handed them to the floor gate, but nothing persisted them. The Writer (`draft_report → load_pool`) and Verifier re-read the pool **from Postgres**, where every `attached_primary_url` was still `NULL` → the floor passed on enriched in-memory data while the Writer drafted from un-enriched DB data. Every quant claim was therefore a guaranteed I3 violation (`has_primary_trace: false` for the entire pool).
2. **The Writer freely drafted quant claims from unbacked quotes.** Once (1) was fixed, the ~10 primary-backed quotes became visible — but they are a needle in a haystack of thousands of unbacked quant quotes. DeepSeek kept reaching for the abundant unbacked numbers; the prompt's Law-3 instruction can't reliably overrule a ~99%-unbacked pool.

## What was done

| # | Module | What it does | Revert |
|---|---|---|---|
| 1 | `storage/repo.py` | **`persist_enriched(conn, sources)`** — re-upserts each enriched `Source` so `attached_primary_url` lands in the DB before the Writer's `load_pool` reads it. Wired into `scout/enrich.py::enrich_primary_live` (which already received `conn` but never used it). No-op on `[]`. | delete `persist_enriched` + its call in `enrich_primary_live` |
| 2 | `writer/select.py` (new) | **`eligible_pool(pool)`** — drops quantitative quotes lacking a primary trace (kept iff non-quant, or `attached_primary_url`, or `source.is_primary`); drops sources left with no quotes. Wired as one line in `writer/runner.py::draft_report` after `load_pool`. | delete `writer/select.py`, the import, and the one `pool = eligible_pool(pool)` line in `draft_report` (revert comment is inline) |

## Key invariants

- **Structural I3 guarantee (not a nudge).** With `eligible_pool`, every quant quote remaining in the Writer's pool is primary-backed, so any claim citing a quant quote *necessarily* has a primary → I3 (`verifier/checks.py::check_quant_has_primary`) becomes structurally unviolable. Faithful to Law 3: a quant quote with no primary can never lawfully appear, so it is removed rather than offered to the model.
- **Same pool to Writer and Verifier.** `draft_report` filters once; the filtered `pool` flows into both `assemble()` (the prompt) and the `DraftBundle` the Verifier checks — no Writer/Verifier divergence.
- **Floor gate untouched.** The floor runs earlier, on the full enriched in-memory pool (`grounded/primary/outlets`); the filter only narrows the Writer's draft input. `primary≥1` at the floor is unaffected.
- **Accepted trade-off — thinner brief.** The brief leans on the ~10 backed numbers + qualitative context instead of the rich unbacked pool. Given current primary-tracing recall, that *is* the honest lawful brief; a thin lawful report beats a rich unlawful one (financial Iron Law).

## How to test

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -p no:cacheprovider -q \
  tests/scout/test_repo.py tests/scout/test_enrich.py \
  tests/writer/test_select.py tests/writer/test_draft_bundle.py tests/writer/test_repo_writer.py
```

- `tests/scout/test_repo.py::test_persist_enriched_survives_load_pool_roundtrip` — DB round-trip: an enriched `attached_primary_url` survives `load_pool` (RED was `None` vs the URL).
- `tests/writer/test_select.py` — pure filter logic (drop unbacked quant, keep backed-quant / non-quant / `is_primary`-source quant, drop emptied sources).
- DB-backed tests require the dockerized Postgres up (`docker compose up -d postgres`).

## Out of scope / still open — the recall lever

The filter makes the pipeline **lawful**; it does not make the brief **rich**. Richness needs more primary-backed quotes surviving the filter — i.e. higher primary-tracing recall. Today the *only* live route to a primary-backed quote is "secondary outlet → cninfo PDF whose number matches" (`source.is_primary` is defined and honored by the Verifier but **never set `True` anywhere in gather/enrich** — that branch is dead live). Higher-leverage follow-ups, in order:

- **G1.1** activate the DeepSeek fallback classifier (`enrich.py::_classify` is stubbed to `None`; quotes only enter the funnel via strict rules now) — likely the biggest recall unlock.
- **Gather official venues directly + set `is_primary=True`** (cninfo / SSE `sse.com.cn` / SZSE / CSRC `csrc.gov.cn` for constituents) — activates the dead `is_primary` path; a quote pulled straight from an official disclosure *is* primary, no fragile PDF number-match.
- **Bias Bocha queries toward primary domains** (`site:cninfo.com.cn`-style variants / boost official-domain hits, then mark `is_primary`).
- **G1.2** non-cninfo tracers (exchange `减持` / regulator `政策`) still yield no attach.
