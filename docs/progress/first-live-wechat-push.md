# First live WeChat push — I10 unblocked, report delivered

> **Read when:** the live `--send-real` run fails Verifier check **I10** (RF-7 cross-claim contradiction) or crashes at the label step (`labeled message length … exceeds 500`); or working on the Writer prompt rules, the verify-fail observability path, or the live `_draft`/label wiring in `scheduling/__main__.py`.

**Status:** complete, 2026-07-07. **Milestone: the first real autonomous morning report was pushed to WeChat and confirmed received by the owner.** Four surgical, independently revertible changes found while driving the first push — targeted bug fixes, not a phase (no spec/plan).

**Why:** after the I3 publish-path work (`writer-i3-publish-path.md`) let the floor and Verifier I3 pass, `--send-real` still could not publish. Two content defects tripped Verifier **I10**, and once those cleared a third, downstream **label-budget** wiring bug crashed the send. All three are now fixed; a `--dry-run` rehearsal reaches `published` and the real `--send-real` push succeeded end-to-end.

## What was done, by task

| Area | Module | What it does | Commit |
|---|---|---|---|
| Number fidelity | `writer/prompt.py`, `tests/writer/test_prompt.py` | Prompt rule: render every figure EXACTLY as its source quote states it — same digits, same unit; never unit-convert-and-round (a source's `17539.73万元` must stay `17539.73万元`, never `1.75亿元`). Rounding broke the source's own arithmetic and tripped I10. | `a70287d` |
| Self-contained claims | `writer/prompt.py`, `tests/writer/test_prompt.py` | Prompt rule: every `claim.statement` must name its own subject (股票/公司/指数); never `该股/该公司/该指数/它/其` as a stand-in for a subject named in another claim. Claims are verified in isolation, so a subject-less claim mis-binds to a neighbor. | `a70287d` |
| Rejected-draft observability | `migrations/0005_rejected_drafts.sql`, `storage/repo.py`, `orchestration/runner.py`, `scheduling/run_once.py`, `scheduling/dispatch.py`, `scheduling/__main__.py`, tests | On any verify-fail, persist the full `WriterOutput` as JSON to `rejected_drafts` (keyed by `trace_id`) alongside `claim_failures`. `record_fail` widened to 3-arg `(trace_id, violations, output)` and threaded through the whole publish chain. | `091c815` (core), `7fe469f` (live wiring) |
| Label-budget wiring | `scheduling/__main__.py` | The live `_draft` closures now render at `max_chars = MAX_TOTAL - len(label_prefix)` (P1c design intent that was never wired to the live closures), so body + DEV label ≤ 500 and `apply_label` only prepends. | `7fe469f` |
| Stale-fixture fix | `tests/scout/test_cninfo_pdf.py` | Fixture returned a bare `_DETAIL_OK` where the caller expects a list; changed to `[_DETAIL_OK]`. Carried over from the prior session. | `7d5939e` |

## Diagnosis (how the I10 root cause was pinned)

The I10 judge sees only claim statements and is **fail-closed**. The question was whether it false-positives on any two same-domain claims, or correctly flags a genuinely ambiguous one. A three-way judge experiment settled it:

| Draft pair | Judge violations |
|---|---|
| actual draft (南芯涨停 + 盛美 +16%, distinct subjects) | 0/3 |
| ambiguous (南芯涨停 + `该股…涨幅15%`) | 3/3 |
| explicit (南芯涨停 + `盛美上海…涨幅15%`) | 0/3 |

**Conclusion:** the judge is correctly subject-aware; it does not conflate two different stocks. The defect was the **Writer** emitting a non-self-contained claim (`该股…15%`) that the judge reasonably bound to 南芯's 涨停 → contradiction. The Verifier correctly blocked publication. Fix belongs in the Writer prompt, **not** in loosening the judge.

## Key invariants

- **Self-contained claims.** Each `claim.statement` names its own subject, because every claim is verified in isolation. A subject-less claim (`该股/它/其…`) is the root cause of the 涨停-vs-15% I10 false-contradiction; naming the subject removes the mis-binding.
- **Number fidelity.** Figures are rendered exactly as the source states them; unit-convert-and-round is forbidden. Rounding loses precision and breaks the source's internal arithmetic, which surfaces as an I10 contradiction between two claims drawn from the same source.
- **Rejected drafts are captured, not discarded (obvious-fail).** Every verify-fail now writes the full draft to `rejected_drafts` keyed by `trace_id`, so a blocked report is inspectable after the fact. Closes the observability gap where `bundle.output` was thrown away on the fail path.
- **Label budget reserved at render.** The body is rendered at `MAX_TOTAL − len(label_prefix)`; `apply_label` only prepends and keeps its fail-closed guard. Reserving up front (not truncating after) keeps `render.py` the single orphan-marker-safe owner of truncation.
- **Verifier gate untouched.** These are Writer-input, observability, and wiring fixes. The hardcoded Law-5 verify gate is unchanged — nothing here weakens a check to force a pass.

## Verification

- Offline suites green after each change: **111 passed** (writer + orchestration + scheduling) and **3 passed** (live-Postgres `test_rejected_drafts` + verifier record-failures); **70 passed** (scheduling + `test_label`) after the budget fix.
- Non-sending rehearsal `--dry-run --force-fresh --force-calendar`: **RED** (`ValueError: labeled message length 525 exceeds 500`) → **GREEN** (`published`) after the label-budget fix.
- Live `--force-calendar --force-fresh --send-real`: outcome `published`, real `HermesWeixin` primary, owner confirmed receipt. First real autonomous WeChat morning push.

## Deferred (recorded, not dropped)

- **`tests/prompt_regression/` is still an unbuilt stub (CLAUDE.md §8.3).** Prompt changes here rest on live validation, not a score gate. Building the harness would let self-contained-claim / number-fidelity regressions be caught offline.
- **Optional structural numeric-fidelity Verifier check** (defense-in-depth) — a mechanical check that a rendered figure matches its source quote's digits/unit, complementing the prompt rule.
- **`scheduling/__main__.py` docstring/`prog` still say `run_once`** — a manual re-run via the wrong module name is a silent no-op footgun; cosmetic, untouched here.
