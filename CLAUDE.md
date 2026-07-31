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
- **The harness embeds the superpowers discipline into each brief.** Sub-agents do **not** receive the SessionStart superpowers bootstrap and will not auto-invoke superpowers (`using-superpowers` carries a `<SUBAGENT-STOP>` — a dispatched sub-agent skips the discovery/orchestration meta-skill and just executes its task). They *can* still load a named skill via the Skill tool (verified 2026-06-05: a probe sub-agent loaded `superpowers:test-driven-development` and returned its verbatim content) — but the harness never relies on that. Instead the harness keeps the **process** skills (brainstorming, writing-plans, requesting-code-review, verification-before-completion) and bakes the **execution** discipline (TDD/RED gate, surgical changes, simplicity, the invariants) into each task spec as concrete, checkable instructions. Naming the relevant execution skill in the brief is optional reinforcement, never a substitute for embedding the discipline.
- **Every sub-agent brief is self-sufficient and returns verifiable evidence.** It must stand alone (the sub-agent has none of the parent's context) and must require evidence-back — for implementation, the actual **RED assertion text** and the **GREEN output** — which the harness verifies before accepting. A sub-agent's summary describes intent, not proof; trust but verify.
- **If a sub-agent needs the user's help or a decision it cannot make** (ambiguous spec, a locked decision it wants to change, missing credential), it **STOPS its current work and asks the user** — it does not guess and run.

### Approval gate (harness ↔ user)

- **Phase plans require human approval; sub-agent launches do not.** Every phase plan (P1c, P2a, P2b, P3c, …) requires explicit user approval before implementation begins: the harness writes the plan, then **STOPS and waits**. **Once a plan is approved, sub-agent dispatches are pre-authorized** — the harness launches them (Sonnet, never Haiku) without seeking per-dispatch approval, and only returns to the user for a genuine blocker (a human-in-loop step like a credential/QR login, an ambiguous spec, or a request to overturn a locked decision).
- **Subagent-Driven Development is the DEFAULT execution method — do not ask which approach to use.** Once a plan is approved, the harness executes it via superpowers' subagent-driven-development (fresh Sonnet sub-agent per task + two-stage review: spec-compliance then code-quality, verifying RED+GREEN evidence between tasks). Never offer "subagent vs inline" as a choice or pause to confirm the execution mode; just proceed. Inline execution is used only if the user explicitly asks for it.
- **Plan at the controller's altitude, not the coder's.** Because the harness is *present at every task gate* (it dispatches each sub-agent and reviews RED+GREEN before the next), a plan must NOT pre-write full implementation bodies. Over-specifying code does two harms: it does the sub-agent's thinking for it (wasting a fresh context that reasons better against the real files), and it anchors the harness's review to "did they match my draft?" instead of "is this correct?" — letting planning-time bugs propagate with the harness's authority. Instead, each task fixes the **contract** (exact signatures, types, field names, return shapes — cross-task consistency is the controller's job), the **RED assertion** (the specific behavior each test pins and that it must fail on an assertion for the right reason — an Iron Law, never delegated), and the few **spec-critical literals** (regex token lists, equality rules, magic constants where the spec *is* the value), then **describes** the implementation in tight behavioral prose rather than writing it. Test code may be kept closer to verbatim than implementation code, because the RED assertion is the thing the harness is contractually on the hook for and the thing sub-agents most often soften. Rule of thumb: if the plan could run correctly *without* the harness in the loop, it is over-specified for this execution mode.

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
2. **TDD (Iron Law)**: write the failing test, then **watch it fail on an assertion (or a domain error like `SchemaViolation`) for the expected reason** — a bare `ImportError`/collection error ("module not found") is **not** a valid RED, since it fires identically for a good test and for `assert True` and proves nothing about what the test checks. For a brand-new module, scaffold a minimal stub (the module + the signature returning a wrong sentinel) so the test actually runs, *then* watch the assertion fail; only then write minimal code. **One narrow exception:** a pure construction / smoke-import test (e.g. building a frozen dataclass with no behavior to assert) *is* exercised by the import itself, so an `ImportError` RED is legitimate there — the rule above binds **behavioral** tests (schema, render, prompt, repo, gate logic), where the assertion is the whole value. **After-the-fact check (when in doubt that an existing test discriminates):** mutate the implementation (break the behavior under test) and confirm the test goes red — that is the RED you never watched, run retroactively. The project's "tests" include the `tests/citation_ground_truth/` regression — any Writer/Verifier change must pass the sample set first.
3. **Prompt changes**: run `tests/prompt_regression/` on every Writer-prompt edit; a score below the previous version is not accepted.
4. **Verify before completion (Law 5 spirit)**: before claiming "done/passing", run the actual command, read the full output, confirm, then claim. No command run = cannot claim it passes.
5. **Failure cases**: everything the Verifier rejects goes into `claim_failures`; review weekly and feed it back into the rules.
6. **Document in the same PR — a phase is done when the docs land, not when the tests pass.** Every PR carries its own paper trail; none of it is a follow-up chore. The set:
   - **Spec** — `docs/superpowers/specs/<date>-<name>-design.md`, the brainstorm output (what shape, and why that one). Skip it *only* when the design was already locked upstream (a `CITATION_CONTRACT.md` invariant, an existing ADR), and then **say so in the progress note**, naming where the design actually lives. Silence reads as an omission.
   - **Plan** — `docs/superpowers/plans/<date>-<name>.md`.
   - **Progress note** — `docs/progress/<phase>.md`: what each module does, its commit, the invariants it proves, how to test, out of scope. Lightweight — a table plus a few bullets, not a second design doc. Template: `docs/progress/P1a-scout.md`.
   - **Close what it closes.** If the work resolves a `docs/GAPS.md` entry, or part of one, move it to *Recently closed* **in the same PR** and say what of it stays open. If it changes an approach, add the `DECISIONS.md` ADR. A shipped fix whose gap is still listed open is how the same work gets planned twice.
   - **A stacked or follow-up PR updates the note it invalidates** rather than leaving the phase note describing behavior it just replaced.

   Self-check before opening the PR: from the repo alone, could someone who wasn't here reconstruct *what changed, why that shape, and what it closed*? If not, it isn't done.
7. **Web-search unknown external errors before guessing**: when an opaque error from a third-party tool/API/SDK shows up — a vendor error code, a cryptic message, surprising library behavior — **search the web before theorizing or coding a fix**. Don't burn cycles guessing or retrying blindly. Worked example (2026-06-07): the WeChat iLink send kept failing with `ret=-2 errmsg=rate limited`; naive reading said "wait out a rate limit" and time-based backoff did nothing. A web search of the `hermes-agent` issue tracker revealed `ret=-2` is a **mislabeled stale-session** signal — the fix is to refresh the session (or retry tokenless), not to wait. The search converted a dead-end into the correct fix and a P2 design item. Treat the wider community's hard-won knowledge as a first-class debugging tool, especially for external/vendor-side failures we can't see the source of.

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
| `docs/GAPS.md` | open gaps by tier + *Recently closed* | choosing what to build next; **closing a gap you just shipped** |
| `docs/superpowers/specs/`, `docs/superpowers/plans/` | per-phase design + implementation plan | starting a phase, or reconstructing why a shape was chosen |

---

## 10. Tech stack

- Python 3.11+ · LangGraph orchestration · FastAPI + MCP · Postgres + Redis
- **LLM: DeepSeek V4 Pro across all roles including the judge; tokens unlimited** (see `DECISIONS.md` D-26, which supersedes the former Sonnet-judge decision)
- Market data: akshare. Crawling: Bocha + Playwright fallback. **Domestic sources only — no crawling of overseas sites** (domestic media coverage of overseas markets is retained; see `ARCHITECTURE.md` Gap 2)
- IM: primary WeChat, backup Feishu (see `DECISIONS.md` D-16)
- Deploy: Docker Compose, single domestic cloud node
- **Git over SSH, not HTTPS.** The China network resets `git`-over-HTTPS to `github.com:443` (`Recv failure: Connection was reset` / connect timeouts); SSH on port 22 is open and reliable. Push/pull over SSH — one-off without touching config: `git push git@github.com:VariianWrynn/marketwind.git master`. (`gh`'s API host `api.github.com` stays reachable even when git-HTTPS is blocked, so `gh issue`/`gh pr` work regardless.)

Build/test commands (fill in after P0):

```
make dev          # bring up local stack
make test         # full test suite
make test-gt      # ground-truth regression
make eval-prompt  # prompt regression
```
