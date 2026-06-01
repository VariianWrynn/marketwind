# Phase Gates

> **Read when:** implementing the Orchestrator or any phase transition.

**Parent**: `CITATION_CONTRACT.md` § 5 (Downstream Module Reference)

Hard gates between pipeline stages. If the prior phase doesn't meet the gate, the next phase does not start. This is the superpowers `systematic-debugging` "must complete each phase before proceeding" pattern applied to this project.

---

## Gate 0: Scout → Writer

**Pre-conditions** (all must be true to pass):

- [ ] `quote_pool` quantitative-eligible quotes ≥ 30
- [ ] `quote_pool` primary-source-attached quotes ≥ 10
- [ ] Time-awareness has written `publish_ts` for every source; I5 all pass
- [ ] All sources pass I9 recency (`ingested_at - publish_ts ≤ 7 days`)
- [ ] Sources span ≥ 5 independent outlets (guards against a pool sourced from a single outlet)

**Fail action**: below threshold → Scout incremental search ≤ 2 rounds; still short → drop that section (no entry to Writer); if sections drop below 3 → degrade the day to an 800-char news digest (see `failure-handling.md § 3`).

---

## Gate 1: Writer → Verifier

**Pre-conditions**:

- [ ] Writer output passes `parser.assert_schema(...)`, I8 passes
- [ ] No Red Flag RF-1 / RF-3 / RF-9 / RF-10 (schema-layer RFs)
- [ ] Every claim_id exists in the Claim table
- [ ] Every source_id exists in the Source table

**Fail action**: any RF fires → reject the whole report, return to Scout for re-fetch + full pipeline re-run. **Do not let the Writer rewrite to route around it** (a self-patch carries the same hallucination).

---

## Gate 2: Verifier → Synthesizer

**Pre-conditions**:

- [ ] All invariants I1–I12 checked
- [ ] Failure rate passes the `failure-handling.md § 3` thresholds
- [ ] `claim_failures` persisted (with `legal_quotes_available`)
- [ ] No Red Flag RF-2 / RF-4 / RF-5 / RF-6 / RF-7 / RF-11
- [ ] No quantitative claim has `corroboration_status = insufficient`
- [ ] (v0.3) I11 cross-report consistency done: today's verified claims compared against the last N days in `pipeline_runs`; conflicts have generated `correction` claims
- [ ] (v0.3) I12 derived-metric check: every `derived_metric` claim carries a `methodology` label

**Fail action**: handle per `failure-handling.md § 3` (re-run / degrade / no-publish); RF hits per `failure-handling.md § 4`.

---

## Gate 3: Synthesizer → IM push

**Pre-conditions** (this is `verification-before-completion` applied at the pipeline layer):

- [ ] **Verification-before-publication**: sample 10 claims at random from the final report, re-run them through the judge (DeepSeek V4 Pro) → all pass
- [ ] `pipeline_runs` written with full trace: `report_id`, `verifier_evidence_blob`, `gate_pass_timestamps`, `attribution_trace`
- [ ] IM channel health check passes (primary + backup)
- [ ] Report rendering passes markdown validity (no broken `[n]`; every `[n]` maps to the source list)
- [ ] No Red Flag RF-8 (only when the report contains follow-up mini-pipeline content)

**Fail action**: any sampled judge check fails → no main-report publish, send a status message with `trace_id`; channel health fails → switch to backup; backup also fails → push status to all reachable channels; rendering invalid → Synthesizer re-runs once; still failing → no publish.

---

## Gate meta-rules

1. Each gate pre-condition maps to a boolean function. Gate pass = all booleans true. No boolean implementation = the pre-condition isn't being checked.
2. **Gate evaluation must leave evidence**: each check's input, output, and boolean result is written to `pipeline_runs.gate_evidence`. A "pass" without evidence counts as not-passed.
3. **No "skip for now"**: any ADR exception must register the specific `trace_id` under the `DECISIONS.md` process, with an expiry ≤ 7 days.
4. **No "partial pass"**: all pre-conditions true = pass. 9/10 ≠ pass.
5. **No reverse jumps between gates**: a Gate 2 failure does not re-run Gate 1 directly; return to the start of the phase that owns the failure cause (typically Scout).

---

## Verification-before-completion mapping

The obra/superpowers `verification-before-completion` five steps:

1. **IDENTIFY**: which boolean function proves this gate?
2. **RUN**: execute it (fresh, no cached result)
3. **READ**: read the full output + exit code
4. **VERIFY**: does the output support the gate pass?
5. **ONLY THEN**: advance to the next phase

Skipping any step = dishonesty, not efficiency.

---

## Anti-patterns

Any of these = a defect, no exception:

- "This source was fine last run, skip the RF-5 check this time"
- "Gate 2 failure rate is 26%, only 1% over the 25% threshold, let it through"
- "Sampling 10 claims at Gate 3 is slow, do 3"
- "The Verifier already ran once, the Synthesizer doesn't need verification-before-publication"
- "Time's almost up, push first and backfill the trace later"

Each is a rationalization an LLM/engineer produces under pressure; see the Iron Rule in `rationalization-table.md`.
