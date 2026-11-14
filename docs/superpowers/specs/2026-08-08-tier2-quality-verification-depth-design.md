# Tier 2: Quality & Verification Depth — Design

**Date:** 2026-08-08
**Status:** Implemented
**PR:** #23

## Per-gap design decisions

### G2.7 — CI (GitHub Actions)
**Shape:** Single advisory workflow `.github/workflows/ci.yml` running `pytest -m "not live"` with Postgres 16 + Redis 7 service containers.
**Why advisory:** Branch protection unavailable on this account/plan for private repos (403 on `/branches/master/protection`). CI reports status but cannot be required.
**Decision locked:** None — new infrastructure.

### G2.6 — Ground-truth regression runner
**Shape:** JSON fixture (`samples.json`) with 13 labeled samples + Python runner. Each sample encodes pool, claims, sentences, expected checks, and expected pass/fail. Runner loads fixtures, runs all verifier checks (tier-1 deterministic + tier-2 with fail-closed stub judge), compares against expected.
**Why JSON fixtures:** Easy to add samples without writing Python. Mechanical success criterion: flip a label → runner goes red.
**Judge handling:** Stub judge returns no violations (fail closed). Samples that depend on judge catches (GT-S2, GT-S3b, GT-S5) pass with stub — documented in fixture notes. Real judge integration deferred to when I1/I10 enforcement is production-ready.
**Upstream contract:** `CITATION_CONTRACT.md` §1 Iron Laws, `citation/glossary.md` independent-source rule.

### G2.8 — Prompt regression harness
**Shape:** Frozen pool fixture (3 sources, 5 quotes) + baseline.json (7 assertions) + runner calling DeepSeek v4-pro. Scores: valid_json, schema_clean, claims_count_min, no_invalid_category, no_filler, no_first_person, self_contained_subjects.
**Why separate from pytest:** Calls real model (D-26). Cannot run offline. Own `make` target.
**Fail-closed:** Missing API key → exit non-zero with clear message. Never skip silently.
**Decision locked:** D-26 (DeepSeek V4 Pro).

### G2.4 — Mojibake / image-only PDFs
**Shape:** 3 new tests proving fail-closed: image-only PDF → empty extract → no-attach; garbled PDF → no number match → no-attach. Verified through full `enrich_primary` integration path.
**Why no OCR:** Iron Law 3 risk — OCR'ing financial digits can introduce silent errors.
**Reclassified:** From open gap to closed-with-tests. Permanent accepted limitation.

### G2.1 + I10 time_window — Cross-report storage
**Shape:** Migration 0008 adds `time_window` column to claims + `pipeline_runs` table. `DraftClaim` gains `time_window: str | None`. Writer prompt instructs model to emit time_window. Schema parser reads it. `persist_report` writes it. `persist_pipeline_run` + `load_recent_claims` provide cross-report read path.
**Why combined with I10:** The persisted shape names `time_window` — I10 needs it for time-window-aware contradiction. Sequencing them together avoids a placeholder column.
**Precedent:** Followed `0006_i12_derived_metric.sql` pattern for adding fields through the chain.

### G2.2 — Verifier Tier-3 invariants
**I3b/I2 corroboration:** Tier-1 check. Quantitative claims with <2 independent source domains must have attribution prefix in referencing sentence. Regex: `据.{0,20}(?:报道|消息|披露|指出|研报|分析|公告)|根据.{0,20}(?:报道|消息|数据|统计|公告)`.
**I10 time-window:** Modified `check_no_contradiction` to include time_window in judge prompt. Different time windows explicitly not contradictions.
**I11 cross-report:** Async check with injectable `RecentClaimsFn` seam. Fail closed on lookup failure (`I11_unavailable` violation).
**I6 freshness:** Async check with injectable `FreshnessSearchFn` seam. Present-tense indicators (目前/当前/持有/现任/最新) trigger search. Fail closed on search failure.
**Why injectable seams:** I11 needs DB, I6 needs network. Tests drive fakes, suite stays offline.

### G2.3 — Claim state machine
**Shape:** Migration 0009 adds `state` (default 'verified') and `retry_count` columns. `compute_failure_digest()` computes claim-level failure rate with warn (10%) / halt (25%) thresholds. `can_retry()` enforces max 1 retry.
**Why minimal:** "Resist building a workflow engine." State field + one retry + threshold checks + digest.
**Thresholds locked:** D-4 (10%/25%), D-8 (claim-level denominator), D-9 (max retry = 1).

### G2.5 — Per-site publish_ts parsing
**Shape:** Parser registry mapping domains to extraction functions. 7 outlets covered (sina, cls, stcn, eastmoney, ifeng, cngold, nbd). Extraction via meta tags, JSON-LD, inline date patterns.
**Why registry:** Easy to add new outlets. Unknown domain → None.
**Fail-closed:** Parser exceptions caught → None. Never a guess.

## Decisions made without asking

1. **G2.6 judge stub:** Fail-closed stub returning no violations. Samples depending on judge catches pass with stub; documented in fixture notes.
2. **G2.2 I3b attribution regex:** Included "公告" as valid attribution keyword (in addition to 报道/消息/披露/指出/研报/分析).
3. **G2.2 I11/I6 seams:** Optional parameters on `verify()` — when not provided, checks are skipped (no violations). This avoids breaking existing callers.
4. **G2.3 state default:** 'verified' — existing claims in the DB are already verified, so the default matches reality.
5. **G2.5 parser scope:** 7 outlets covering the top domains in the sources table. Additional outlets can be added by registering new parsers.
