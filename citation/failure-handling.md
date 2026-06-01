# Failure Handling

> **Read when:** implementing Verifier or Synthesizer failure paths, the claim state machine, or the failure-rate thresholds.

**Parent**: `CITATION_CONTRACT.md` § 4 (Invariants), § 5 (Downstream)

(Rendered output fragments — attribution prefixes, the correction template, the risk disclaimer — and detection strings are kept in Chinese because they appear in or match the Chinese report.)

---

## § 1. Per-claim violation handling

| Failure type | Handling | Scope |
|---|---|---|
| Quantitative (precision/unit) failure | drop claim; delete the whole sentence | claim-level |
| Temporal failure (fiscal period / YoY-vs-QoQ base wrong) | drop claim | claim-level |
| Comparative failure ("首次" and similar qualifiers falsified) | drop claim | claim-level |
| Attribution failure (company/entity relationship wrong) | rewrite to a vague form (相关公司); reissue a new `claim_id` | claim-level (old → dropped, new → drafted) |
| Causal failure (source didn't state the causation) | delete the causal connective, keep facts in parallel; same sentence | sentence-level (claim kept) |
| Freshness failure (I6) | drop, or trace to the latest source and regenerate | claim-level |
| Source unavailable (URL dead / article pulled) → `source_unavailable` | same as freshness: drop or trace | claim-level |
| Quote-pool coverage insufficient | Scout incremental search ≤ 2 rounds; still short → drop the section | section-level |
| Single-source quantitative claim with `is_primary = true` (I3b) | auto-convert to `corroboration_status = attributed_single`; render with a 据 X 报道 prefix | claim-level (legal degradation, not a failure) |
| Synthesis violation (I1 / RF-2) | mark the sentence failed and re-assemble; **claims unchanged** | **sentence-level** |
| Derived metric without methodology (I12) | if base figures exist → fall back to base figures only (e.g. keep 营收508/净利330.12, drop "日赚 3.6 亿"); if insisting on the derived number → force a `methodology` label | claim-level |
| Cross-report conflict (I11) | do not drop. Generate a `correction` claim, render 更正：昨日 X → 今日 Y explicitly; the old claim stays unchanged in history | report-level (adds a correction claim) |
| Time window missing (`time_window = undated`) | return to Scout for time metadata; if unobtainable → drop the claim (can't do the time-window-aware consistency check) | claim-level |

`[uncited]` is never a legitimate degradation path under this contract.

---

## § 2. Claim state machine

```
        ┌─────────┐
        │ drafted │
        └────┬────┘
             │
       ┌─────┴──────┬──────────────────┐
       ▼            ▼                  ▼
   ┌────────┐  ┌────────────────┐  ┌─────────────────────┐
   │verified│  │ failed_<type>  │  │ source_unavailable  │
   └───┬────┘  └────────┬───────┘  └──────────┬──────────┘
       │                │                     │
       │                ▼ (retry_count++)     ▼ (trace latest source)
       │           ┌─────────┐           ┌──────────┐
       │           │rewritten│           │rewritten │
       │           └────┬────┘           └────┬─────┘
       │                │                     │
       │      ┌─────────┴─────────┐           │
       │      ▼                   ▼           │
       │  verified         failed_<type>      │
       │                   (retry = 1)        │
       │                        │             │
       │                        ▼             │
       │                   ┌─────────┐        │
       └──────────────────►│ dropped │◄───────┘
        (to Synthesizer)   └─────────┘
                          (terminal)
```

**Max retry = 1**: a rewritten claim that fails again → forced `dropped`; no infinite loop.

**Key boundary cases**:

- **Synthesis violation (I1 / RF-2) is a sentence-level failure, not a claim-level one.** The claims' status is unchanged; only the sentence is marked failed and re-assembled. This preserves claim traceability in `claim_failures`.
- **Attributed single is not a failure state**: a single-source quantitative claim with `is_primary = true` takes the `corroboration_status = attributed_single` path and stays `drafted → verified`.
- **Source-unavailable merges with freshness**: dead URL / pulled article both record `source_unavailable`, handled like a freshness failure.

---

## § 3. Failure-rate thresholds

### Failure-rate definition

```
failure_rate = (claims with status in {failed_*, dropped, source_unavailable})
             / (all claims drafted in this report)
```

**Denominator** = all claims drafted in this report's generation (including those ultimately dropped).

Notes: `attributed_single` does **not** count as a failure (legal degradation); `verified` does not count; `rewritten` is classified at final evaluation by its final state; sentence-level failure rate is an auxiliary metric only — claims are the atomic unit.

### Weekday thresholds

| Failure rate | Handling |
|---|---|
| < 10% | publish normally |
| 10–25% | Writer re-runs once (same pool, new prompt path); still below bar → degrade to an 800-char digest, explicitly marked 完整版未通过质量阈值 |
| > 25% | Scout re-fetch + pipeline re-run; still over → no main-report publish, status message only |

### Holiday thresholds (policy-dense, tightened 5pp)

| Failure rate | Handling |
|---|---|
| < 5% | publish normally |
| 5–15% | same as weekday 10–25% path |
| > 15% | same as weekday > 25% path |

For claims about policy / regulation / licenses / administrative actions: **force `has_primary = true`** and the primary must be a government site / company announcement / regulatory filing; media re-interpretation cannot be the sole source.

### The "flag-and-publish-anyway" path is abolished

The v0.1 "20% failure → flag but still publish" path was removed in v0.2. Warning fatigue hits the owner too. A below-bar report has no delivery value.

---

## § 4. Red Flag disposition

Any Red Flag firing (see `red-flags.md`):

- **Does not enter the failure-rate statistics**: an RF is a structural violation, not a quality score.
- **Skips the degradation path**: not even the 800-char digest (the degraded version may still carry RF-contaminated content).
- **Goes straight to reject + Scout re-fetch + pipeline re-run.**
- If the same RF fires again → no main-report publish for the day; send a status message with `trace_id` and the RF number.
- `claim_failures` records the offending sentence/claim/source as a Scout blacklist candidate for the next round.

---

## § 5. ConciergeBot out-of-bounds handling

A user follow-up's mini-pipeline is subject to this file too. In particular:

- **RF-8**: ConciergeBot may not cite facts outside the original report's claim store.
- If the asked fact is not in the original claim store → it must trigger a fresh Scout + Writer + Verifier flow; **the LLM may not answer directly.**
- **Investment-advice follow-ups** ("我账户该买啥") use the risk-disclaimer template:

  > 本系统仅做事实核验与信息聚合，不提供投资建议。所有持仓/交易决策应基于您的独立判断。

  This reply does not go through the fact-generation pipeline and is exempt from the contract's claim requirements.

- **Change-cron / change-subscription / regenerate** commands must confirm: ConciergeBot may not directly execute side-effectful operations. An LLM changing a scheduled job is an accident generator.

---

## § 6. Failure case store

All failed / dropped / source_unavailable / Red-Flag-rejected claims are written to `claim_failures`:

| Field | Meaning |
|---|---|
| `claim_id` | original claim id |
| `failure_type` | failure-type enum |
| `failed_at` | timestamp |
| `original_claim_text` | normalized claim statement |
| `original_quote_pool_snapshot` | the full quote pool Scout provided at the time |
| `legal_quotes_available` | the quotes that could legally have supported this claim (annotated by the Verifier at write time; distinguishes "couldn't find" from "found but misused") |
| `final_disposition` | drop / rewrite / regenerated |
| `red_flag_id` | the RF number if an RF fired |
| `trace_id` | links to `pipeline_runs` |
| `meta_violations` | ad-hoc exceptions / skipped checks taken without an ADR |

**Weekly pattern review**: run failure-pattern analysis (manual or automated), feeding back into the Writer prompt's rationalization table, the Scout source blacklist, the Verifier rules, and new traps in the ground-truth set. This is the superpowers "failure cases = the most valuable asset" idea, realized.
