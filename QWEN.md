# QWEN.md — MarketWind (市风)

> **Read when:** first, always. This is the entry point for any agent or developer.

> MarketWind is a STAR50 (科创50) financial morning-report agent. Every pre-market it autonomously generates a fully source-traceable Chinese deep-dive report, pushes it over IM, and supports two-way follow-up. **The report is always written in Chinese; everything else in this repo is in English.**

Read this file, then `CITATION_CONTRACT.md`, then `DECISIONS.md` before doing anything.

---

## 1. Selective reading

Many docs in this repo carry a `> **Read when:** …` line right under their title. **Use it.** Load a doc only when its condition matches your current task — do not slurp the whole repo into context. The hot-load rule in `CITATION_CONTRACT.md` § 6 tells each agent role exactly which companions to load.

---

## 2. How work gets done

### Sub-agent per feature

- **Dispatch a fresh sub-agent (via the `agent` tool) for each feature / task.** Keep the parent context clean; the sub-agent does one unit of work against a clear spec and reports back. The parent orchestrates and reviews; it does not accumulate every file in its own context.
- **Every sub-agent brief is self-sufficient and returns verifiable evidence.** It must stand alone (the sub-agent has none of the parent's context) and must require evidence-back — for implementation, the actual **RED assertion text** and the **GREEN output** — which the harness verifies before accepting. A sub-agent's summary describes intent, not proof; trust but verify.
- **If a sub-agent needs the user's help or a decision it cannot make** (ambiguous spec, a locked decision it wants to change, missing credential), it **STOPS its current work and asks the user** — it does not guess and run.

### Approval gate

- **Phase plans require human approval; sub-agent launches do not.** Every phase plan requires explicit user approval before implementation begins. **Once a plan is approved, sub-agent dispatches are pre-authorized** — launch them without seeking per-dispatch approval, and only return to the user for a genuine blocker.
- **Plan at the controller's altitude, not the coder's.** A plan must NOT pre-write full implementation bodies. Each task fixes the **contract** (exact signatures, types, field names, return shapes), the **RED assertion** (the specific behavior each test pins), and the few **spec-critical literals** (regex token lists, equality rules, magic constants), then **describes** the implementation in tight behavioral prose rather than writing it.

---

## 3. Before you write any code

There is a root spec (`CITATION_CONTRACT.md`) and a decision log (`DECISIONS.md`) recording many already-debated, locked decisions. **Do not re-litigate locked decisions.** To overturn one, go through the `DECISIONS.md` ADR process with evidence — do not quietly swap approaches in the implementation.

This is a **financial** system. A wrong number, treating yesterday's fact as today's, or passing a model's guess off as fact — the reader (first the project owner) acts on it with real money. The error budget is an order of magnitude tighter than ordinary information aggregation.

---

## 4. Behavioral principles

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
7. **Web-search unknown external errors before guessing**: when an opaque error from a third-party tool/API/SDK shows up — a vendor error code, a cryptic message, surprising library behavior — **search the web before theorizing or coding a fix**. Don't burn cycles guessing or retrying blindly.

---

## 9. Document map

| File | Role | Read when |
|---|---|---|
| `QWEN.md` (this) | entry, principles, boundaries | first |
| `CITATION_CONTRACT.md` | root spec: Iron Laws, data model, invariants (v0.5) | before any report logic |
| `citation/rationalization-table.md` | writer excuse/rebuttal table | when writing the Writer prompt |
| `citation/red-flags.md` | whole-report reject conditions | when writing the Verifier |
| `citation/phase-gates.md` | pipeline stage gates | when writing the Orchestrator |
| `citation/failure-handling.md` | violation handling, state machine, thresholds | when writing Verifier/Synthesizer |
| `citation/glossary.md` | single source of terms | throughout |
| `ARCHITECTURE.md` | 6-layer, agent boundaries, known gaps | when designing a module |
| `DECISIONS.md` | locked decisions + ADR process | before changing any approach |
| `DEPLOY.md` | agent-facing deploy + operate runbook (gates, prohibited ops, escalation) | deploying or operating the ECS report node |
| `tests/citation_ground_truth/samples.md` | 12 labeled samples (RED baseline) | when writing Verifier tests |
| `docs/progress/<phase>.md` | per-sub-phase "what was done" notes | picking up / resuming a built layer |
| `docs/GAPS.md` | open gaps by tier + *Recently closed* | choosing what to build next; **closing a gap you just shipped** |
| `docs/superpowers/specs/`, `docs/superpowers/plans/` | per-phase design + implementation plan | starting a phase, or reconstructing why a shape was chosen |

---

## 10. Tech stack

- **Language**: Python 3.11+
- **Orchestration**: LangGraph DAG
- **API**: FastAPI + uvicorn
- **Database**: Postgres 16 (asyncpg) + Redis 7
- **LLM**: DeepSeek V4 Pro across all roles including the judge (see `DECISIONS.md` D-26); OpenAI-compatible API
- **Market data**: akshare
- **Crawling**: Bocha search API + Playwright (headless Chromium) fallback. **Domestic sources only — no crawling of overseas sites**
- **IM**: primary WeChat (hermes CLI), backup WeCom webhook (see `DECISIONS.md` D-16, ADR-0002)
- **Deploy**: Docker Compose, single domestic cloud node (Aliyun ECS)
- **Scheduling**: APScheduler (dual cron + interval + event triggers)
- **PDF extraction**: pypdf (cninfo disclosure PDFs)
- **Testing**: pytest + pytest-asyncio (asyncio_mode = "auto")
- **Linting**: ruff (Python), sqlfluff (SQL migrations, dialect = postgres)

### Build/test commands

```bash
# Local dev stack
make dev              # docker compose up --build

# Tests (run from repo root, DATABASE_URL/REDIS_URL default to localhost)
make test             # pytest (full suite, ~349 tests)
pytest tests/scout/   # run a single module's tests
pytest tests/writer/
pytest tests/verifier/
pytest tests/scheduling/

# SQL lint
make lint-sql         # sqlfluff lint migrations

# Database migrations (applied automatically by docker compose; manual only for host dev)
make migrate          # python -m marketwind.storage.migrate

# Manual pipeline runs
python -m marketwind.scheduling                     # one-shot real send
python -m marketwind.scheduling --dry-run            # route to StubSink
python -m marketwind.scheduling --floor-only         # probe grounded floor, zero LLM tokens
python -m marketwind.scheduling --scheduler          # persistent daemon
python -m marketwind.scheduling --force-calendar     # run on non-trading day (implies --dry-run)
python -m marketwind.scheduling --force-fresh        # bypass freshness window (off-hours rehearsal)

# Ground-truth regression (STUB — not yet implemented, G2.6)
make test-gt          # exit 1

# Prompt regression (STUB — not yet implemented, G2.8)
make eval-prompt      # exit 1
```

---

## 11. Project structure

```
marketwind/
├── config.py              # pydantic-settings runtime config (reads .env)
├── scout/                 # NewsScout: multi-source fetch + primary-trace
│   ├── gather.py          #   gather_live: Bocha search + Playwright fetch
│   ├── fetch.py           #   page-level fetch with Chromium
│   ├── enrich.py          #   enrich_primary_live: cninfo primary trace
│   ├── primary.py         #   trace_to_primary: cninfo disclosure lookup
│   ├── cninfo_pdf.py      #   PDF download + text extraction
│   ├── source_tier.py     #   5-tier domain authority model (ADR-0003)
│   ├── claim_extract.py   #   extract quantitative claims from raw text
│   ├── market.py          #   STAR50 constituent list + market data (akshare)
│   ├── calendar.py        #   trading calendar service
│   ├── runner.py          #   evaluate_floor: grounded-floor gate check
│   ├── outlets.py         #   domain classification (quote aggregator filter)
│   ├── query.py           #   per-name constituent query builder
│   ├── numbers.py         #   numeric normalization
│   ├── amount.py          #   amount-guard for primary trace
│   └── domain.py          #   Source, Quote, FloorResult dataclasses
├── writer/                # EditorialWriter: grounded generation
│   ├── prompt.py          #   build_writer_prompt: Iron Laws + rationalization inline
│   ├── client.py          #   call_deepseek: OpenAI-compatible LLM call
│   ├── writer.py          #   draft_report orchestration
│   ├── runner.py          #   draft_report: pool → prompt → LLM → parse → remap
│   ├── schema.py          #   Writer output JSON schema validation
│   ├── select.py          #   eligible_pool: pre-filter by source tier
│   ├── render.py          #   render_brief + render_source_tail
│   ├── domain.py          #   PooledSource, PooledQuote, DraftClaim, WriterOutput, DraftBundle
│   └── diagnostics.py     #   writer output diagnostics
├── verifier/              # FactChecker: I1–I12 + Red Flags
│   ├── checks.py          #   5 deterministic Tier-1 checks (no LLM)
│   ├── judge.py           #   call_judge: LLM-based semantic verification
│   ├── verifier.py        #   verify: checks + judge → pass/fail
│   ├── runner.py          #   call_judge entrypoint
│   └── domain.py          #   Violation, VerifyResult
├── orchestration/         # Pipeline runner
│   └── runner.py          #   run_pipeline: floor → draft → verify → push
├── scheduling/            # Autonomous triggering layer
│   ├── __main__.py        #   CLI entrypoint (--scheduler, --floor-only, --dry-run)
│   ├── scheduler.py       #   build_scheduler: APScheduler dual cron
│   ├── dispatch.py        #   dispatch_job + catch_up (boot reconciliation)
│   ├── run_once.py        #   run_once: single pipeline execution with gates
│   ├── anchor.py          #   anchor_utc: DST-aware pre-market anchor
│   ├── trigger.py         #   Trigger protocol (cron-only seam today)
│   ├── deadman.py         #   dead-man's switch Healthchecks check-in
│   ├── outcome.py         #   RunOutcome: PUBLISHED / SUB_FLOOR / VERIFY_FAIL
│   └── calendar_gate.py   #   trading-day gate
├── gateway/               # IM + API layer
│   ├── app.py             #   FastAPI app (/health endpoint)
│   └── im/                #   IM channel adapters
│       ├── base.py        #     IMChannel protocol + SendResult
│       ├── factory.py     #     build_channels: config-driven selection
│       ├── hermes_weixin.py #   HermesWeixin: send_weixin_direct Python API (ADR-0001 overturned)
│       ├── wecom_webhook.py #  WecomWebhook: session-less webhook
│       ├── bark_alert.py  #     BarkAlert: iOS push on delivery failure
│       ├── stub.py        #     StubSink: dev/test no-op
│       └── label.py       #     DEV_PREFIX, apply_label, MAX_TOTAL
├── storage/               # Persistence
│   ├── repo.py            #   asyncpg repository (run_ledger, claim_failures, etc.)
│   └── migrate.py         #   one-shot migration runner (ADR-0004)
migrations/                # SQL migrations (0001–0007), applied at boot
citation/                  # Contract companion docs (loaded at runtime by Writer/Verifier)
tests/                     # ~77 test files, pytest + pytest-asyncio
deploy/
├── report-node/           # Production ECS deployment (compose override, Dockerfile, checks)
└── deadman-fc/            # Aliyun FC serverless dead-man watcher
docs/
├── adr/                   # Architecture Decision Records (0001–0004)
├── progress/              # Per-phase progress notes
└── GAPS.md                # Master gap register
```

---

## 12. Key domain concepts

### Source tiers (ADR-0003)

5-tier domain authority model in `marketwind/scout/source_tier.py`:

| Tier | Name | Clears I3 gate | Earns ✓官方核实 badge |
|---|---|---|---|
| 4 | OFFICIAL | ✓ | ✓ |
| 3 | DESIGNATED | ✓ | ✓ |
| 2 | TRUSTED | ✓ | ✗ |
| 1 | SECONDARY | ✗ | ✗ |
| 0 | EXCLUDED | ✗ | ✗ |

- **primary-grade** (`clears_law3`): `attached_primary_url OR is_primary OR tier ≥ TRUSTED`
- **officially-verified** (`is_officially_verified`): `… OR tier ≥ DESIGNATED`

### Pipeline & gates

```
Scout ──Gate0──► Writer ──Gate1──► Verifier ──Gate2──► Synthesizer ──Gate3──► IM push
```

- **Gate 0** (Scout→Writer): ≥30 quant-eligible quotes, ≥10 primary-attached, ≥5 independent outlets, I5/I9 pass
- **Gate 1** (Writer→Verifier): schema parse (I8), no RF-1/3/9/10, all IDs resolve
- **Gate 2** (Verifier→Synthesizer): I1–I12 checked, failure-rate < threshold, no RF-2/4/5/6/7/11
- **Gate 3** (Synthesizer→IM): sample 10 claims re-judged, pipeline_runs written, IM health check, rendering valid

### Verifier checks (Tier-1 deterministic, in `verifier/checks.py`)

1. `check_quotes_resolve` — RF-3/RF-9: quote_id re-resolution against raw_content spans
2. `check_quant_has_primary` — I3/RF-6: quantitative claims need primary-grade source
3. `check_no_filler_attribution` — RF-4: no anonymous filler phrases (据报道, 业内人士, etc.)
4. `check_no_first_person_inference` — RF-10/Law-4: no system first-person inference
5. `check_derived_methodology` — I12: derived_metric claims must carry methodology

### Writer prompt architecture (`writer/prompt.py`)

- Inlines Iron Laws + rationalization table as self-correction guardrail
- Pool serialized with short aliases (`q1…`, `s1…`) not raw UUIDs (D-31)
- Law 3 clarification: pool is pre-filtered, `has_primary_trace=false` ≠ fails Law 3
- Category whitelist: quantitative, temporal, comparative, attribution, causal, quoted_inference, freshness, derived_metric, correction
- Output: JSON `{claims: [...], sentences: [...]}`, no markdown fences, no `[n]` markers

### IM channel architecture (`gateway/im/`)

- `IMChannel` protocol: `send(text) → SendResult(ok, error)`
- `build_channels(settings) → (primary, fallback)` driven by `im_channel` config
- ADR-0001 (overturned 2026-08-05): HermesWeixin calls hermes' `send_weixin_direct` Python API directly
- BarkAlert: out-of-band iOS push when primary delivery fails (fire-and-forget, never blocks pipeline)
- ADR-0002: WeChat (hermes) is unattended primary, WeCom-webhook is backup
- `_send_soft`: try primary, fallback, log-only on ref failure (never blocks PUBLISHED)

### Scheduling & dispatch (`scheduling/`)

- Dual cron: pre-market (DST-anchored to US close + 2h ET) + 07:00 CST main report
- `dispatch_job`: per-job execution with retry, idempotency guard (`_already`), dead-man check-in
- `catch_up`: boot reconciliation — checks if today's report was missed during downtime
- `run_once`: single pipeline execution with freshness/calendar gates
- Trading calendar: `akshare` `tool_trade_date_hist_sina` + local cache fallback

---

## 13. Git & network

- **Git over SSH, not HTTPS.** The China network resets git-over-HTTPS to `github.com:443`. SSH on port 22 is open and reliable.
  - Push/pull: `git push git@github.com:VariianWrynn/marketwind.git master`
  - `gh` CLI API (`api.github.com`) stays reachable even when git-HTTPS is blocked.
- **Remote**: `git@github.com:VariianWrynn/marketwind.git`
- **Main branch**: `master`

---

## 14. Positioning

**This is a demo/learning + personal-use project, not a production 24×7 system.**

- Cut speculative production weight: complex Watchdog, canary releases, object-storage archival.
- Keep: grounded citation, multi-source corroboration, citation quality, self-correction, cross-day correction.
- Anti-pattern: "heavier than a demo, more fragile than production" — do not return to that state.
- **Outward positioning**: describe what the system *does* — grounded generation + full source traceability + cross-day consistency. Never claim a "market gap" or "no one has done this".
