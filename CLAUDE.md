# CLAUDE.md — MarketWind (市风)

> **Read when:** first, always. This is the entry point for any agent or developer.

> MarketWind is a STAR50 (科创50) financial morning-report agent. Every pre-market it autonomously generates a fully source-traceable Chinese deep-dive report, pushes it over IM, and supports two-way follow-up. **The report is always written in Chinese; everything else in this repo is in English.**

Read this file, then `CITATION_CONTRACT.md`, then `DECISIONS.md` before doing anything.

---

## 0. Required plugins — find them or fail

This project is built to run with two plugins **assumed present**:

- **superpowers** (obra) — the brainstorming → writing-plans → TDD → code-review methodology.
- **karpathy-guidelines** — the four behavioral principles (below).

**At session start, actively locate both** (via skill discovery / plugin listing). **If either is missing, STOP and report an error to the user.** Do not proceed without them — degrading silently to ad-hoc behavior is exactly the failure these guardrails prevent.

---

## 1. Selective reading

Many docs in this repo carry a `> **Read when:** …` line right under their title. **Use it.** Load a doc only when its condition matches your current task — do not slurp the whole repo into context. The hot-load rule in `CITATION_CONTRACT.md` § 6 tells each agent role exactly which companions to load.

---

## 2. How work gets done — sub-agent per feature

Following the get-shit-done (open-gsd/get-shit-done-redux) design logic and superpowers' subagent-driven-development:

- **Dispatch a fresh sub-agent for each feature / task.** Keep the parent context clean; the sub-agent does one unit of work against a clear spec and reports back. The parent orchestrates and reviews; it does not accumulate every file in its own context.
- **At the start of every task, the sub-agent actively invokes superpowers** and follows the appropriate flow (brainstorming for new features, systematic-debugging for bugs, TDD for implementation, etc.).
- **If a sub-agent needs the user's help or a decision it cannot make** (ambiguous spec, a locked decision it wants to change, missing credential), it **STOPS its current work and asks the user** — it does not guess and run.

---

## 3. Before you write any code

There is a root spec (`CITATION_CONTRACT.md`) and a decision log (`DECISIONS.md`) recording many already-debated, locked decisions. **Do not re-litigate locked decisions.** To overturn one, go through the `DECISIONS.md` ADR process with evidence — do not quietly swap approaches in the implementation.

This is a **financial** system. A wrong number, treating yesterday's fact as today's, or passing a model's guess off as fact — the reader (first the project owner) acts on it with real money. The error budget is an order of magnitude tighter than ordinary information aggregation.

---

## 4. Behavioral principles (Karpathy)

**① Think before coding.** Don't assume, don't hide confusion, surface tradeoffs.
- When multiple interpretations exist, list them — don't silently pick one.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop, name what's confusing, ask.

**② Simplicity first.** Minimum code that solves the problem; nothing speculative.
- No "flexibility" or "configurability" that wasn't asked for.
- 200 lines that could be 50 → rewrite. Ask: "would a senior engineer call this overcomplicated?"
- **Watch for over-engineering here specifically**: per `DECISIONS.md` this is a demo/learning + personal-use project, not a 99%-uptime production system. Cut speculative Watchdog complexity, object-storage archival, and elaborate multi-tier fallbacks.

**③ Surgical changes.** Touch only what you must; clean up only your own mess.
- Don't "improve" adjacent code, comments, or formatting. Don't refactor things that aren't broken.
- Notice unrelated dead code → mention it, don't delete it.
- Test: every changed line traces directly to the current task.

**④ Goal-driven execution.** Define success criteria; loop until verified.
- "add validation" → "write tests for invalid inputs, then make them pass".
- Strong success criteria let you loop independently; weak ones ("make it work") force constant clarification.

---

## 5. The Iron Laws (from `CITATION_CONTRACT.md` § 1)

Any code that generates, verifies, or publishes report content is bound by these five:

```
1. NO FACTUAL SENTENCE WITHOUT A CLAIM_ID
2. NO CROSS-CLAIM SYNTHESIS IN A SINGLE SENTENCE
3. NO QUANTITATIVE CLAIM WITHOUT A PRIMARY SOURCE
4. NO MODEL-GENERATED INFERENCE — EVER
5. NO PUBLICATION WITHOUT FRESH VERIFIER PASS
```

**Violating the letter is violating the spirit.** Catch yourself thinking "this time is different" → stop.

---

## 6. Autonomous triggering & long-running operation — a core feature

This is not a script you run by hand. **Self-triggering and durable, unattended operation are defining features of the project**, and a large part of why it exists (vs. a one-shot prompt). Treat the scheduling/triggering layer as first-class, not plumbing:

- **Dual cron** (see `DECISIONS.md` D-18): a pre-market brief (anchored to US close + 2h, not a fixed clock time) and the 07:00 main report.
- **Unified `Trigger` protocol**: cron / interval (keyword polling) / event (Redis Streams). New triggers implement the protocol and register — no change to the main flow.
- **Trading-calendar service** so holiday/weekend runs degrade correctly instead of emitting empty reports.
- **Durable run loop**: the system wakes itself, runs the pipeline through the gates, and either publishes or emits a status message with a `trace_id` — without a human in the loop.

When designing any module, ask how it behaves under unattended, repeated, calendar-aware triggering — not just when invoked once.

---

## 7. Never do

- **Never** let the Writer emit free-form text outside the `(sentence, claim_ids, source_ids)` schema (I8).
- **Never** let any LLM generate a judgment the source didn't state (Law 4). The only exception, quoted_inference, must carry attribution.
- **Never** bypass a Phase Gate (`citation/phase-gates.md`). A gate that doesn't pass does not advance; there is no "skip for now".
- **Never** publish without a fresh Verifier pass (Law 5). "It passed last time" doesn't count.
- **Never** let ConciergeBot directly execute side-effectful commands (change cron, change subscription) — it must confirm first.
- **Never** pass yesterday's cached data off as today's without an explicit label.
- **Never** claim "no one has done this / market gap" in any outward-facing material.

---

## 8. Development workflow

1. **Before each module**: read the relevant `CITATION_CONTRACT.md` § + the companions that module loads.
2. **TDD (Iron Law)**: write the failing test, then **watch it fail on an assertion (or a domain error like `SchemaViolation`) for the expected reason** — a bare `ImportError`/collection error ("module not found") is **not** a valid RED, since it fires identically for a good test and for `assert True` and proves nothing about what the test checks. For a brand-new module, scaffold a minimal stub (the module + the signature returning a wrong sentinel) so the test actually runs, *then* watch the assertion fail; only then write minimal code. The project's "tests" include the `tests/citation_ground_truth/` regression — any Writer/Verifier change must pass the sample set first.
3. **Prompt changes**: run `tests/prompt_regression/` on every Writer-prompt edit; a score below the previous version is not accepted.
4. **Verify before completion (Law 5 spirit)**: before claiming "done/passing", run the actual command, read the full output, confirm, then claim. No command run = cannot claim it passes.
5. **Failure cases**: everything the Verifier rejects goes into `claim_failures`; review weekly and feed it back into the rules.
6. **Document after each sub-phase**: when a dev sub-phase completes, write a short progress note in `docs/progress/<phase>.md` — what each module does, its commit, and the invariants it proves. Keep it lightweight (a table + a few bullets), not a full design doc. See `docs/progress/P1a-scout.md` for the template.

---

## 9. Document map

| File | Role | Read when |
|---|---|---|
| `CLAUDE.md` (this) | entry, principles, boundaries | first |
| `CITATION_CONTRACT.md` | root spec: Iron Laws, data model, invariants (v0.4) | before any report logic |
| `citation/rationalization-table.md` | writer excuse/rebuttal table | when writing the Writer prompt |
| `citation/red-flags.md` | whole-report reject conditions | when writing the Verifier |
| `citation/phase-gates.md` | pipeline stage gates | when writing the Orchestrator |
| `citation/failure-handling.md` | violation handling, state machine, thresholds | when writing Verifier/Synthesizer |
| `citation/glossary.md` | single source of terms | throughout |
| `ARCHITECTURE.md` | 6-layer, agent boundaries, known gaps | when designing a module |
| `DECISIONS.md` | locked decisions + ADR process | before changing any approach |
| `tests/citation_ground_truth/samples.md` | 12 labeled samples (RED baseline) | when writing Verifier tests |
| `docs/progress/<phase>.md` | per-sub-phase "what was done" notes | picking up / resuming a built layer |

---

## 10. Tech stack

- Python 3.11+ · LangGraph orchestration · FastAPI + MCP · Postgres + Redis
- **LLM: DeepSeek V4 Pro across all roles including the judge; tokens unlimited** (see `DECISIONS.md` D-26, which supersedes the former Sonnet-judge decision)
- Market data: akshare. Crawling: Bocha + Playwright fallback. **Domestic sources only — no crawling of overseas sites** (domestic media coverage of overseas markets is retained; see `ARCHITECTURE.md` Gap 2)
- IM: primary WeChat, backup Feishu (see `DECISIONS.md` D-16)
- Deploy: Docker Compose, single domestic cloud node

Build/test commands (fill in after P0):

```
make dev          # bring up local stack
make test         # full test suite
make test-gt      # ground-truth regression
make eval-prompt  # prompt regression
```
