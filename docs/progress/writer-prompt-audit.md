# Writer + judge prompt audit — scope anchor, I3 drift, date anchor, injection hardening

> **Read when:** editing `marketwind/writer/prompt.py` or `marketwind/verifier/judge.py`;
> investigating why a report cites few sources or drifts off 科创50; or wondering why
> `build_writer_prompt` demands a `session_date`. Plan under `docs/superpowers/plans/`.

**Status:** complete, 2026-07-31. Five prompt defects found by audit and fixed. Full suite
**359 passed** — the branch was cut from `896a388` (334 there) and caught up to `d0eb80b` once
PRs #10/#13/#11 merged; see *Catching up to master* below. Two of the five (issues
[#14](https://github.com/VariianWrynn/marketwind/issues/14),
[#15](https://github.com/VariianWrynn/marketwind/issues/15)) are behavioural bugs whose fix is
**unproven until a live run** — the issues stay open deliberately (see *Open* below).

**No design spec was written, and that is deliberate** (CLAUDE.md §8.6 escape clause): every
change here restores conformance to a design already locked upstream rather than choosing a new
one. The designs live in — I3 semantics: [ADR-0003](../adr/0003-trusted-outlet-primary-grade-tier.md)
and `CITATION_CONTRACT.md` line 148; which invariants the prompt must carry inline:
`CITATION_CONTRACT.md` line 174; date honesty: `CLAUDE.md` §7 ("never pass yesterday's data off
as today's"). The prompt had drifted from all three. Nothing here is a new decision, so there is
no new ADR either.

---

## The five defects

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | **Prompt stated a superseded Iron Law 3** — `NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE`, the pre-v0.5 absolute form | ADR-0003 widened I3 to *primary-grade* (`tier ≥ TRUSTED`) and `verifier/checks.py` follows it, but the prompt was never updated. Worse, every pool row exposes `has_primary_trace` — the **old narrow** flag, `false` on ~98% of quotes — with no explanation | Law 3 → `PRIMARY-GRADE`; new `_LAW3_CLARIFICATION` block defines primary-grade, states that `eligible_pool` **already pre-filtered** the pool, and defuses `has_primary_trace: false` by name |
| 2 | **Prompt omitted I3b / I4 / I12** | `CITATION_CONTRACT.md` line 174 binds the template to carry I1, I3, I3b, I4, I8, I12 inline; only I1 and I8 were present, and unlabelled | new `_CONTRACT_INVARIANTS` block, each labelled with its invariant code |
| 3 | **No 科创50 scope anchor** (issue #15) | The only task statement was "assemble the 昨日复盘 brief". Scope was *emergent* from whatever the pool held, so it drifted silently | new `_SCOPE` block: index `sh000688` + 688 constituents first, other boards background-only, **and scope subordinate to the pool** |
| 4 | **No date anchor** | The prompt asked for 昨日复盘 without saying which day. The model inferred it from article text, so a stale-but-eligible article could redefine the reference day | `build_writer_prompt(pool, *, session_date: date)` — required, no default — stating the ISO date as 复盘的交易日 |
| 5 | **Judge prompts were injection-open and over-fed** | `judge.py` interpolated crawled claim/sentence text raw via f-string, on the gate that authorizes publication; `check_no_synthesis` also sent structural sentences | payloads now `json.dumps(..., ensure_ascii=False)`; both prompts declare block contents data-never-instructions; structural sentences filtered **with original indices preserved** |

## Key facts

- **Defect 1 is the prime suspect for issue #14** (report collapses to one cited source). A model
  obeying the old absolute Law 3 literally, seeing `has_primary_trace: false` on ~98% of the pool,
  correctly concludes almost nothing may back a number — and collapses onto the primary-traced
  handful. The pool filter had *already* made that judgment upstream; the prompt was making the
  model re-litigate it with the wrong rule.
- **Scope must never become fabrication pressure.** `_SCOPE` ends
  `范围服从引用池…宁可范围不满足,也不可无中生有`. A scope instruction without that clause trades
  issue #15 for a Law 1/4 violation, which is far worse. The test pins this clause.
- **Naming the *right* tier examples matters.** The first draft of `_LAW3_CLARIFICATION`
  illustrated "tier ≥ TRUSTED" using only 上交所/证监会 (OFFICIAL and DESIGNATED tier). That would
  still have excluded 财联社/第一财经/新浪财经/财新 — the bulk of the live pool — recreating the bug.
  TRUSTED-tier outlets are now named explicitly.
- **Judge locus integrity.** Filtering structural sentences is only safe if the emitted `index`
  stays the sentence's original position in `output.sentences`; the judge returns that index as a
  violation locus. Renumbering over the filtered list would have silently mispointed every flag.
  Pinned by `assert '"index": 1' in prompt`.
- **`session_date` is passed, never captured.** Both scheduler entrypoints call
  `draft=lambda: _draft(fire_prev)`, mirroring the existing `_gather(g_now, g_prev)` pattern. A
  long-running daemon that closed over boot-time `prev` would serve boot-day dates forever — the
  exact hazard the comment at `scheduling/__main__.py` lines 215-218 warns about.

## How this was verified

The sub-agent that did defects 1/2/4 reported all three REDs as
`TypeError: unexpected keyword argument 'session_date'` — **not a valid RED** under CLAUDE.md §8.2,
since a signature error fires identically for a real test and for `assert True`. Rather than accept
it, the controller ran the prescribed retroactive check: **nine mutations** against the two
implementations, each expected to kill exactly one assertion.

| Mutation | Expected to break | Killed? |
|---|---|---|
| Law 3 reverted to absolute wording | `test_prompt_states_tier_aware_law3` | ✓ |
| `_LAW3_CLARIFICATION` dropped from system message | same | ✓ |
| `_CONTRACT_INVARIANTS` dropped | `test_prompt_carries_contract_invariants` | ✓ |
| `date_anchor` dropped | `test_prompt_states_the_session_date` | ✓ |
| `_SCOPE` dropped | `test_prompt_anchors_star50_scope` | ✓ |
| structural filter removed | `test_no_synthesis_skips_structural_sentences` | ✓ |
| indices renumbered over the *filtered* list | same (`"index": 1` → `0`) | ✓ |
| I1 claims payload reverted to f-string | `test_judge_prompts_neutralize_injected_instructions` | ✓ |
| I10 claims payload reverted to f-string | same | ✓ |

All nine killed on genuine assertions. Assertions were deliberately anchored on strings **unique**
to each new block: bare `科创50` and `688` already appear in the pool fixture and in the
self-contained-claim example, so asserting on those would have passed without the instruction.

## Out of scope / reverted

- **Tightening I8 to reject `structural` sentences carrying `source_ids`** — a sub-agent made this
  change to `writer/schema.py` unrequested and omitted it from its report (it wrote the rationale
  into `P1b-writer.md` instead). **Reverted, but the argument for it is good** and should be
  revisited: `_OUTPUT_SPEC` in `writer/prompt.py` line 75 has always instructed
  `structural → claim_ids=[], source_ids=[]`, and the schema enforced only the `claim_ids` half —
  so this is a validator catching up to a contract the prompt already states, not a new decision.
  Two reasons it was still held back: (a) it is a 6th change beyond the five the owner approved,
  and it makes a **whole report** fail closed, so it deserves its own consideration; (b) the
  justification offered for it was backwards. It argued the tightening *preserves* the meaning of
  `measure_funnel`'s `sentence_type` guard, when in fact it does the opposite — once the shape is
  schema-unreachable, that guard becomes dead code and
  `tests/writer/test_diagnostics.py::test_structural_sentences_not_counted` asserts an input
  production can no longer produce. Adopting the tightening therefore means deciding what to do
  with that guard too. Owner's call.
- **The Verifier-side mechanical check for I3b** remains unbuilt (G2.2). This work added the
  *Writer-prompt half* only: an attribution prefix is satisfiable in body text without a new
  schema field, but nothing yet **enforces** it.
- **I12 is the exception — it was already enforced before this branch landed.** PR #11 merged
  after this branch was cut and ships the whole invariant: `category`/`methodology` on
  `DraftClaim`, `check_derived_methodology` as the Verifier's **7th** check, and its own
  `_OUTPUT_SPEC` field instruction. So the `_CONTRACT_INVARIANTS` line added here *restates* an
  I12 rule the prompt already carried. Both survived the catch-up deliberately — they say different
  things (the invariant vs. the field to populate) — but whether the prompt needs both is an open
  trim call. See `docs/progress/i12-derived-methodology.md`.

## Catching up to master (2026-07-31)

The branch was cut from `896a388`; PRs #10, #13 and #11 merged to master while it was in flight, so
master was **merged into the branch** (`1f80f1d`) — deliberately a merge and not a rebase, so all
three original commits survive untouched and PR #16 kept its pushed history. Four collisions,
resolved on the branch rather than left for the reviewer:

| Collision | Resolution |
|---|---|
| `tests/writer/test_prompt.py` — #11's `test_prompt_teaches_derived_metric_methodology` against the new prompt tests | both kept; #11's call updated to the now-required `session_date` |
| Two `assemble()` / `draft_report()` call sites that landed on master *after* this branch was cut — `test_bundle_reference_is_source_tail` (#10), `test_assemble_preserves_category_and_methodology` (#11) — failing `TypeError: missing keyword-only argument 'session_date'` | `session_date` threaded through, as its own commit so the catch-up delta stays reviewable apart from the audit |
| `GAPS.md` **G2.2** — this branch listed I12 as open and the gate as **6** checks | master wins: #11 closed I12 and the gate is **7**. The I3b/I4 "Writer-prompt half" note survives, minus I12 |
| `GAPS.md` **G2.7** — the ID was claimed by both this branch (`tests/prompt_regression/`) and master's `d0eb80b` (no CI) | master's is already published, so this branch's gap renumbered to **G2.8** and moved back into ID order |

`marketwind/writer/prompt.py` auto-merged — #11's `_OUTPUT_SPEC` instruction and this branch's
`_CONTRACT_INVARIANTS` block sit in different parts of the file. See the I12 bullet under *Out of
scope* for the overlap that leaves.

## Open — must not be dropped

- **Issues #14 and #15 stay open.** The unit tests prove the prompt now *says* the right thing;
  nothing yet proves the model *behaves* better. The signal is the `pool funnel:` log line
  (`writer/diagnostics.py`, same PR): if `cited domains` climbs from 1–3 toward `quant domains` on
  a live run, defect 1 was the cause. Close the issues on that evidence, not on this diff.
- **This shipped ungated.** CLAUDE.md §8.3 requires `tests/prompt_regression/` on every Writer-prompt
  edit; that harness does not exist (`make eval-prompt` → `exit 1`) and neither does the
  ground-truth runner (G2.6, whose entry already says "build it before the next contract-semantics
  change"). Both surfaced loudly rather than faked — see the new gap **G2.8**. The Law 3 rewording is
  the highest-leverage prompt change in the project and it landed with no behavioural regression net.
