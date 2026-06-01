---
name: citation-builder
description: Use when generating, verifying, or rendering any factual content for the morning report — drafting report sentences, attaching citations, running claim verification, or handling user follow-up questions. Enforces the Citation Contract's Iron Laws and routes to the right companion docs. Do NOT use for non-factual structural content (titles, transitions) or pure ops tasks.
---

# citation-builder

Runtime projection of `CITATION_CONTRACT.md`. Any agent that touches report facts must pass through here first.

## The Iron Laws (non-negotiable)

```
1. NO FACTUAL SENTENCE WITHOUT A CLAIM_ID
2. NO CROSS-CLAIM SYNTHESIS IN A SINGLE SENTENCE
3. NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE
4. NO MODEL-GENERATED INFERENCE — EVER
5. NO PUBLICATION WITHOUT FRESH VERIFIER PASS
```

**Violating the letter is violating the spirit.** Thinking "this time is different" → stop.

## Load by role

| You are | Must read | Output contract |
|---|---|---|
| Writer | main contract § 1/§ 2, `citation/rationalization-table.md` | `(sentence, claim_ids, source_ids)` JSON list; no free-form text (I8) |
| Verifier | main contract § 3.4/§ 4, `citation/red-flags.md`, `citation/failure-handling.md` | one verdict + evidence per claim |
| Synthesizer | main contract § 2/§ 3.5, `citation/phase-gates.md` (Gate 3) | rendered report + Gate 3 pass evidence |
| ConciergeBot | `citation/failure-handling.md § 5` (RF-8, out-of-bounds) | routing result; side-effectful commands must confirm |

## Mandatory order

1. **Write no fact from general knowledge.** Assemble only from Scout's quote pool.
2. **Every factual sentence**: bind ≥1 claim_id → ≥1 quote_id → ≥1 source_id.
3. **Quantitative claim**: must have a primary source (announcement/report/regulatory/official); single-source → convert to `attributed_single` with a 据 X 报道 prefix.
4. **Derived metric** (日赚/合计/排名): carry a `methodology` basis or use only base figures.
5. **Inference**: only the source's own quoted_inference + attribution. Self-synthesis = Law 4 violation.
6. **Before completion** (Law 5): run a fresh Verifier, read the full output, confirm, then claim a pass. No command run = no claim.

## Model

The judge and all generation use **DeepSeek V4 Pro** (tokens unlimited). Weak/local models may serve high-tolerance helpers (ranking, normalization), never the judge.

## Red Flags (a hit = reject whole report, no patch)

Anonymous filler attribution (据报道/业内人士/市场认为), cross-claim synthesis, fabricated quote_id, system first-person inference (系统认为/经测算), stale content as fresh. Full table in `citation/red-flags.md`.

## Anti-rationalization

Catch yourself thinking "too basic to cite" / "reads better merged" / "common-knowledge number" / "the Verifier will catch it" → all are violation precursors. Full rebuttals in `citation/rationalization-table.md`.
