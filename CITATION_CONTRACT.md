# Citation Contract

> **Read when:** before touching any report-generation, citation, or verification logic. This is the root spec; all module specs, prompts, verifier rules, and skills must reference it.

**Status**: Active · **Version**: 0.5 · **Last Updated**: 2026-06-17
**Scope**: Root spec for the MarketWind (市风) morning-report agent.

**v0.5 changelog** ([ADR-0003](docs/adr/0003-trusted-outlet-primary-grade-tier.md)): I3's `has_primary` is now satisfied by a **primary-grade** source — a 5-tier source-authority model (`marketwind/scout/source_tier.py`) treats CSRC-designated (Tier 3) and curated-trusted (Tier 2) disclosure outlets as able to back a quantitative claim, since the live Tier-0 supply is near zero (Bocha can't reach cninfo). The Tier-0 "Primary source" definition is **unchanged**; a mechanical `✓官方核实` reader badge (tier ≥ DESIGNATED) keeps the genuine-primary signal honest. The contract bump was **not** mechanically regression-gated — the `tests/citation_ground_truth/` runner is unbuilt (gap G2.6); surfaced loudly, not faked. See glossary "Source tiers".

**v0.4 changelog**: model layer is now DeepSeek V4 Pro across all roles including the judge (supersedes the former Sonnet-judge decision; tokens are unlimited so the cost gate is dissolved). Overseas-site crawling is dropped, but domestic-media coverage of overseas markets is retained. See `DECISIONS.md`.

**v0.3 changelog** (driven by audit of a real quote pool; evidence in `tests/citation_ground_truth/samples.md`): I6 freshness widened from "subject attributes" to "rolling numeric state with a present-tense indicator"; added Claim categories `derived_metric` and `correction`; added `time_window` field and made I10 / RF-7 time-window-aware; added I11 (cross-report consistency) and I12 (derived-metric methodology).

---

## § 0. Document Status

This contract is the project **root spec**. Every downstream module (Grounded Generation / Financial Claim Verifier / Time-Awareness / Synthesizer / ConciergeBot) must satisfy these invariants in both its spec and its implementation. Any code, prompt, or output that violates the contract is a defect to be fixed, not tolerated.

`.claude/skills/citation-builder/SKILL.md` is the runtime projection of this document. Detailed rules live in the companion files listed in § 6.

---

## § 1. The Iron Laws

```
1. NO FACTUAL SENTENCE WITHOUT A CLAIM_ID
2. NO CROSS-CLAIM SYNTHESIS IN A SINGLE SENTENCE
3. NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE
4. NO MODEL-GENERATED INFERENCE — EVER
5. NO PUBLICATION WITHOUT FRESH VERIFIER PASS
```

**Violating the letter of these laws is violating the spirit.**

If you (writer / verifier / any LLM call) catch yourself reasoning "this case is different because…", you are about to violate. **Stop.** Every legitimate exception is already captured under the ADR process; an exception without an ADR is a violation. Common writer rationalizations are catalogued in `citation/rationalization-table.md`.

The only legitimate "inference" is **quoted inference**: the source itself made the inference in its own text, and the writer preserves attribution when quoting it (e.g. 据 XX 证券研报观点). Stripping the attribution and presenting it as the system's own view violates Law 4.

---

## § 2. Sentence Dichotomy

Every sentence that enters the final report belongs to exactly one of two classes; there is no third:

- **Factual sentence**: contains ≥ 1 factual claim; must carry ≥ 1 `claim_id`.
- **Structural sentence**: titles, transitions, section lead-ins, date stamps — carries no factual claim.

"Half-fact half-opinion", "impressionistic generalization", and "uncited summary" are all violation states. `[uncited]` is never a legitimate degradation path.

### Single Claim Chain (the operating rule for Law 2)

A factual sentence may cite multiple sources (corroboration), but those sources must all support **the same claim**. Cross-claim factual synthesis is forbidden.

**Violation (example output):**
> 比亚迪 IGBT 出货超越英飞凌，且毛利率下滑 2.3pp [1][2]
> ([1] reports shipments, [2] reports margin — two claims fused into one sentence)

**Compliant rewrite:**
> 比亚迪 IGBT 出货量超越英飞凌 [1]。同期毛利率较 Q2 下降 2.3 个百分点 [2]。

---

## § 3. Data Model

### § 3.1 Traceability Granularity

```
sentence
  └─ claim_id (≥ 1)
      └─ quote_id (≥ 1)
          └─ source_id (≥ 1)
              └─ url, publish_ts (ISO 8601 + tz),
                 domain, byline, is_primary,
                 raw_span_start, raw_span_end
```

report_id + claim_id must reverse-resolve any sentence to its original URL and raw-text span.

### § 3.2 Source

| Field | Type | Constraint |
|---|---|---|
| `source_id` | UUID | PK |
| `url` | text | not null; validated reachable at ingest time |
| `domain` | text | derived from url |
| `byline` | text | nullable (editorial / staff pieces) |
| `publish_ts` | timestamptz | ISO 8601 + tz; raw strings forbidden |
| `is_primary` | bool | true = announcement / financial report / regulatory filing / official channel (see `citation/glossary.md`) |
| `raw_content` | text | full article archive |
| `ingested_at` | timestamptz | Scout ingest time |

### § 3.3 Quote

| Field | Type | Constraint |
|---|---|---|
| `quote_id` | UUID | PK |
| `source_id` | UUID | FK |
| `text` | text | original sentence |
| `span_start`, `span_end` | int | char offsets into raw_content |
| `context_before`, `context_after` | text | one sentence on each side |
| `quote_type` | enum | `factual` / `quoted_inference` / `data` |

### § 3.4 Claim

| Field | Type | Constraint |
|---|---|---|
| `claim_id` | UUID | PK |
| `quote_ids` | UUID[] | ≥ 1 |
| `category` | enum | `quantitative` / `temporal` / `comparative` / `attribution` / `causal` / `quoted_inference` / `freshness` / `derived_metric` / `correction` |
| `statement` | text | normalized statement |
| `time_window` | enum | `overnight_us` / `us_extended` / `cn_prev_session` / `cn_intraday` / `point_in_time` / `period` / `policy_event` / `undated` (see glossary) |
| `corroboration_count` | int | de-duplicated per the glossary independent-source rule |
| `corroboration_status` | enum | `corroborated` (≥2) / `attributed_single` (=1, render with 据 X prefix) / `insufficient` |
| `has_primary` | bool | whether ≥ 1 primary source is attached |
| `methodology` | text | nullable; required for `derived_metric` (e.g. 按净利润计) |
| `status` | enum | `drafted` / `verified` / `failed_<type>` / `rewritten` / `dropped` / `source_unavailable` |
| `retry_count` | int | default 0, max 1 |

**DB CHECK constraints** (enforced at write, not derived):
- `(category = 'quantitative') IMPLIES (has_primary = true)`
- `(category = 'quantitative') IMPLIES (corroboration_count >= 2 OR corroboration_status = 'attributed_single')`
- `(category = 'derived_metric') IMPLIES (methodology IS NOT NULL)`

State-machine transitions and failure handling: see `citation/failure-handling.md`.

### § 3.5 Sentence

| Field | Type | Constraint |
|---|---|---|
| `sentence_id` | UUID | PK |
| `report_id` | UUID | FK |
| `claim_ids` | UUID[] | factual ≥ 1; structural = 0 |
| `rendered_text` | text | final text with [n] markers |
| `sentence_type` | enum | `factual` / `structural` |
| `position` | int | order within report |

---

## § 4. Invariants

Violating any invariant → auto-reject. Exemptions go through the ADR process (see `DECISIONS.md`).

| ID | Invariant | Where checked | Verification function |
|---|---|---|---|
| **I1** | All claims cited by one sentence must be semantically aligned (no cross-claim synthesis) | Verifier post-write | `verifier.check_no_synthesis(sentence)` |
| **I2** | A claim's `corroboration_count` is de-duplicated per the glossary independent-source rule; reprints/aggregation do not add to the count | Verifier pre-write | `verifier.compute_corroboration(claim)` |
| **I3** | `quantitative` claims must have `has_primary = true` — (v0.5, [ADR-0003](docs/adr/0003-trusted-outlet-primary-grade-tier.md)) `has_primary` is satisfied by a **primary-grade** source (`tier ≥ TRUSTED`, per `source_tier.clears_law3`) as well as a true attached primary or `is_primary`; an unknown/EXCLUDED domain still fails | DB CHECK | `verifier.check_quant_has_primary(claim)` |
| **I3b** | `quantitative` claims must have `corroboration_count ≥ 2` or `corroboration_status = 'attributed_single'` (single-source quant must carry an attribution prefix) | DB CHECK | `verifier.check_quant_corroboration(claim)` |
| **I4** | No model-generated inference; only `quoted_inference` is allowed, and source attribution must be preserved in the body text | Writer prompt + Verifier | `verifier.check_inference_attribution(claim, sentence)` |
| **I5** | Source `publish_ts` must be ISO 8601 + tz | Scout ingest | `scout.validate_timestamp(source)` |
| **I6** | (v0.3, widened) Subject-attribute claims (executives / subsidiary ownership / licenses / regulatory status) **and rolling numeric-state claims carrying a present-tense indicator (目前/现/截至) such as shareholding %, capacity, order backlog** must trigger a 90-day change search | Verifier freshness branch | `verifier.check_freshness(claim)` |
| **I7** | Failed claims must be written to `claim_failures` (with quote-pool snapshot and `legal_quotes_available`) | Verifier on reject | `verifier.persist_failure(claim)` |
| **I8** | Writer output is a list of `(sentence, claim_ids, source_ids)` triples; free-form text forbidden | Writer output schema | `parser.assert_schema(writer_output)` |
| **I9** | Source `ingested_at - publish_ts ≤ 7 days` (prevents stale content being ingested as fresh) | Scout ingest | `scout.check_recency(source)` |
| **I10** | (v0.3, changed) No contradictory factual statements between claims in the same report; **contradiction is time-window-aware: only when two claims share the same `time_window` and subject** | Verifier post-write | `verifier.check_internal_consistency(report)` |
| **I11** | (v0.3, new) Today's verified claims must be compared against published claims of the last N days; on conflict, generate a `correction` claim and flag it explicitly — silently changing the story is forbidden | Verifier post-write (reads `pipeline_runs`) | `verifier.check_cross_report(report, history)` |
| **I12** | (v0.3, new) `derived_metric` claims (a source's computation over base data, e.g. 日赚, 合计减持额) must carry a `methodology` label or state the basis in the body; writing a bare derived number is a violation | Verifier post-write | `verifier.check_derived_methodology(claim)` |

An invariant without a verification function is just words on a page.

---

## § 5. Downstream Module Interface Contract

Every downstream module spec must explicitly reference the relevant contract sections, and every reference maps to an executable test.

| Module | Sections referenced | Verifying tests (paths) |
|---|---|---|
| Grounded Generation spec | § 1 (Laws 1, 2, 4), § 2, § 3.3, § 3.4, § 4 (I1, I2, I3, I3b, I4, I8) | `tests/grounded_gen/T-I1-*`, `T-I2-*`, ... |
| Financial Claim Verifier spec | § 3.4, § 4 (all), `citation/failure-handling.md` | `tests/verifier/T-I1-*` ... `T-I12-*` |
| Time-Awareness spec | § 3.2, § 3.4 (time_window), § 4 (I5, I6, I9, I10, I11), `citation/failure-handling.md` (holiday rules) | `tests/timeawareness/T-I5-*`, `T-I6-*`, `T-I9-*`, `T-I11-*` |
| Synthesizer spec | § 2, § 3.5, `citation/phase-gates.md` (Gate 3), `citation/failure-handling.md` | `tests/synthesizer/T-gate3-*` |
| Writer prompt template | § 1 (Iron Laws inline), § 4 (I1, I3, I3b, I4, I8, I12 inline), `citation/rationalization-table.md` (inline) | `tests/prompt_regression/baseline.json` |

If any module spec conflicts with this contract, the contract wins. Every claim of compliance = one verifying test; no test = an empty promise.

---

## § 6. Companion Documents

The main contract stays lean. Detailed rules load on demand. Each companion begins with a `> **Read when:**` line so an agent can decide whether to load it.

| File | Content | Loaded by |
|---|---|---|
| `citation/rationalization-table.md` | Writer rationalizations + rebuttals | Writer prompt (inline, mandatory) |
| `citation/red-flags.md` | Hard conditions that reject the whole report | Verifier |
| `citation/phase-gates.md` | Entry/pass conditions for each pipeline gate | Orchestrator |
| `citation/failure-handling.md` | Per-claim handling + state machine + failure-rate thresholds + Red Flag disposition | Verifier, Synthesizer |
| `citation/glossary.md` | Term definitions (Primary, Independent, time_window, derived_metric, ...) | everyone, as the single source of terms |
| `DECISIONS.md` | ADR process, locked decisions, version management | when revising |

**Hot-load rule**: the Writer loads the main contract + rationalization-table, not red-flags (not its job). The Verifier loads the main contract + red-flags + failure-handling, not rationalization-table (it should not see the writer's excuse list). This is the superpowers-style "load relevant skill, not all skills" pattern.
