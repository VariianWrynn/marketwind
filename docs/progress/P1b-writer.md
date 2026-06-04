# P1b — Writer (grounded assembly)

> **Read when:** picking up Writer work, or before starting a layer that consumes rendered briefs (P1c IM push).

**Status:** complete. Branch `p1b-writer` (→ `master`). Plan: `docs/superpowers/plans/2026-06-01-p1b-writer.md`.

**What P1b delivers:** read the persisted quote pool, ask DeepSeek v4-pro to assemble a **grounded** brief as `(sentence, claim_ids, source_ids)` triples (Iron Law I8 — no free-form text), schema-validate the output, render a ≤500-char Chinese brief with `[n]` citation markers (no orphans), and persist `claims` + `sentences`. Pure logic is unit-tested offline against a stubbed LLM call (24 tests); the live DeepSeek call is `# pragma: no cover` and exercised by a manual smoke. No Verifier in P1 — the Writer prompt embeds the Iron Laws + `citation/rationalization-table.md` inline as the only guardrail, and the output is schema-checked before rendering.

## What was done, by sub-phase

| Sub-phase | Module | What it does | Commit |
|---|---|---|---|
| Domain | `writer/domain.py` | `PooledSource`/`PooledQuote`, `DraftClaim`/`DraftSentence`, `WriterOutput`, `RenderedSentence`/`RenderedBrief` value objects | e25af36 |
| Load pool | `storage/repo.py` (`load_pool`) | read-side: sources+quotes with real DB UUIDs (Writer input) | 2c45809 |
| Schema (I8) | `writer/schema.py` | `parse_and_validate`: JSON → `WriterOutput`; resolve every id; reject free-form / unresolvable ids (`SchemaViolation`) | 5d2cc60 |
| Render | `writer/render.py` | `[n]` from `source_ids` (first-appearance order); ≤500-char whole-sentence tail-drop; footnotes recomputed so no orphan markers | aed95fe |
| Prompt | `writer/prompt.py` | Iron Laws + rationalization-table inline; grounded-only (D-1); exact JSON schema; serialized pool | 0434b01 |
| Client | `writer/client.py` | pure `parse_chat_completion` (unit-tested) + live `call_deepseek` (httpx, OpenAI-compatible) | 8d8f48b, 14d299e |
| Assemble | `writer/writer.py` | prompt → injected `call` → I8 validate → **alias→UUID remap** (D-31) | 7e9ef39, ed9e6dd |
| Persist + runner | `storage/repo.py` (`persist_report`), `writer/runner.py` | local-claim-id → UUID mapping; insert claims (referenced by kept sentences) + sentences; `run_writer` ties load→assemble→render→persist | 060d15d |
| Live smoke | `scripts/smoke_p1b.py` (gitignored) | real end-to-end chain on the persisted pool; saves the raw response fixture | (not committed) |

Token/timeout budget fix (14d299e): DeepSeek v4-pro is a reasoning model — `max_tokens` 8000→16000, timeout 120→180, so the content survives the reasoning budget.

## Key invariants proved here

- **I8 schema enforcement (fail-closed):** free-form text, a factual sentence without a `claim_id`, a structural sentence carrying one, and any unresolvable `claim_id`/`quote_id`/`source_id` are all rejected as `SchemaViolation` — the whole report fails, never partial-publishes (≈ RF-1).
- **Grounded-only (D-1):** the Writer assembles solely from the serialized pool; the prompt forbids general-knowledge fill.
- **No orphaned markers:** `[n]` is renderer-assigned (never LLM-emitted); over-length drops whole trailing sentences and renumbers, so every surviving `[n]` resolves to a footnote.
- **≤500-char tail-drop:** the brief is bounded by dropping whole trailing sentences, never a mid-sentence cut.
- **D-31 alias mapping:** the Writer cites short pool aliases (`q1…`, `s1…`); aliases are mapped back to real DB UUIDs *after* I8 validation. This removes a pure mechanical failure mode (LLM mis-transcribing a 36-char UUID) without loosening D-1 — still pool-only, still fail-closed. Verified live: the 58-quote pool that previously rejected over a one-char UUID slip now validates cleanly.
- **local-id → UUID claim mapping:** the Writer's invented `c-001`-style ids are mapped to real `claim_id` UUIDs on persist; claims whose sentence was tail-dropped are not written (no orphan claims).

## How to test

```bash
docker compose up -d postgres redis
.venv/Scripts/python.exe -m marketwind.storage.migrate
.venv/Scripts/python.exe -m pytest tests/writer -v   # pure tests need no DB; test_repo_writer.py needs Postgres
```

Whole repo (P1a + P1b, no regressions): `.venv/Scripts/python.exe -m pytest tests/scout tests/writer -v`.

Live chain (needs `OPENAI_API_KEY` + a populated pool from `smoke_p1a.py`):
`PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/smoke_p1b.py`.

**Re-run idempotency note:** unlike Scout's upsert-by-url, `persist_report` uses a fresh `report_id` each run — a report is a point-in-time artifact, so re-running adds a new report. That is expected, not a leak.

## Out of scope / known gaps

- **Verifier + I1–I12, corroboration_count/status, freshness (I6/I11), `derived_metric` methodology, cross-report consistency, attributed_sentiment** — all P2. P1b ships I8 + grounded-only; the deeper invariants are the Verifier's job.
- IM push (P1c) consumes the rendered brief + footnotes — not in this phase.
- Live per-site response shapes: one saved fixture (`tests/writer/fixtures/deepseek_live_smoke.json`) captured for a future offline real-markup test.
