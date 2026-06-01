# Red Flags — Stop and Restart

> **Read when:** implementing the Verifier or the Orchestrator reject logic.

**Parent**: `CITATION_CONTRACT.md` § 4 (Invariants)

Any Red Flag firing = reject the whole report, trigger Scout re-fetch + full pipeline re-run.

**No patch, no partial accept, no Verifier self-repair.** A Red Flag is a structural violation, not a quality issue.

(Trigger phrases are listed in Chinese because they are literal detection strings matched against the Chinese report text.)

| # | Trigger | Violates | Detected at |
|---|---|---|---|
| **RF-1** | Writer output contains free-form text outside the `(sentence, claim_ids, source_ids)` schema | I8 | Writer → Verifier entry, schema parse |
| **RF-2** | A sentence's `claim_ids` actually point to different factual claims (synthesis detection) | I1 / Law 2 | Verifier per-sentence |
| **RF-3** | A claim's `quote_id` has no matching span in its source's `raw_content` (writer fabricated a quote_id) | I8 | schema parse |
| **RF-4** | A factual sentence uses an anonymous filler attribution with no specific source: 据报道、业内人士、市场认为、普遍预期、通常来说、分析人士、知情人士、接近 X 的人士、有消息称 | Law 1 | Verifier per-sentence regex + semantic |
| **RF-5** | Any source `ingested_at - publish_ts > 7 days` (Scout pulled stale content as fresh) | I9 | Scout ingest |
| **RF-6** | A quantitative claim is single-source, `is_primary = false`, and not marked `attributed_single` (media single-source quant not routed through attribution) | I3 / I3b | Verifier corroboration |
| **RF-7** | ≥ 2 claims in the same report contradict on a number/fact and both are `verified`. **(v0.3) Contradiction is time-window-aware: fires only when the two claims share the same `time_window` and subject; opposite statements in different windows are not a contradiction** | I10 | Verifier post-write consistency |
| **RF-8** | ConciergeBot, answering a follow-up, cites a fact not in the original report's claim store and not in this follow-up's mini-pipeline claim store | Law 1 (extension) | ConciergeBot pre-send |
| **RF-9** | A quote's `context_before + text + context_after` fails to re-assemble against the source `raw_content` (quote is hallucinated or the source was rewritten) | I8 | schema parse |
| **RF-10** | The report contains system first-person inference phrasing: 系统认为、分析显示、综合判断、经测算、研究表明 | Law 4 | Verifier per-sentence |
| **RF-11** | A claim's `quote_ids` include ≥ 1 quote from a source on the `claim_failures` source blacklist (repeatedly falsified historically) | historical quality signal | Verifier corroboration |

---

## Detection-time quick map

| When | Red Flags |
|---|---|
| Scout ingest | RF-5 |
| Writer → Verifier schema parse | RF-1, RF-3, RF-9 |
| Verifier per-sentence | RF-2, RF-4, RF-10 |
| Verifier corroboration | RF-6, RF-11 |
| Verifier post-write consistency | RF-7 |
| ConciergeBot pre-send | RF-8 |

---

## Red Flag disposition

See `failure-handling.md` § 4. Key points: a Red Flag does **not** enter the failure-rate statistics (it's a hard veto, not a score); on a hit, **skip the degradation path** (don't even send the 800-char digest), go straight to Scout re-fetch + full pipeline re-run; if the same RF fires again, do not publish the main report for the day — send a status message with `trace_id` and the RF number. `claim_failures` records the offending sentence/claim/source as a blacklist candidate for the next Scout round.

---

## Meta-rules

- A new RF must first have a corresponding counter-example in the ground-truth set, verified to trigger detection.
- Removing/loosening an RF requires an ADR with evidence the RF had 0 hits over the last 30 days.
- Any ad-hoc "skip the RF check this time" = a contract violation, recorded in `claim_failures.meta_violations`.
