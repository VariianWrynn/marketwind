# MarketWind 市风

> **Read when:** for project orientation and the phase roadmap.

> A STAR50 (科创50) financial morning-report agent: every pre-market it autonomously generates a **fully source-traceable** Chinese deep-dive report, pushes it over IM, and supports two-way follow-up.

## What it is

Every factual sentence in the report can be reverse-resolved to its original URL and raw-text span. Quantitative data is forced back to a primary source. The model is not allowed to fabricate any judgment the source didn't state. The output report is in Chinese; the codebase and docs are in English.

The core is not "broadcasting" — it's a **Citation Contract** plus adversarial verification:

- **Sentence dichotomy** — every factual sentence carries a citation; no impressionistic generalizations.
- **Single claim chain** — never fuse two articles' facts into one sentence.
- **Zero silent inference** — the only legal inference is the source's own, with attribution preserved.
- **Cross-day correction** — when today's data overturns yesterday's report, correct it explicitly; never change the story silently.
- **Derived-metric methodology** — derived numbers ("日赚 X 亿") must carry their basis or use only base figures.

## Why these constraints

In a financial setting, a wrong number, treating yesterday's fact as today's, or passing a model guess off as fact — the reader acts on it with real money. The error budget is an order of magnitude tighter than ordinary information aggregation, so the system is built around traceability and adversarial verification rather than fluency.

## Autonomous, unattended operation is a defining feature

MarketWind is not a script you run by hand. Self-triggering, calendar-aware, durable unattended operation is first-class (dual cron, trading-calendar service, a unified trigger protocol, a self-driving run loop that publishes or emits a status message without a human in the loop). See `ARCHITECTURE.md` § 2.

## Repository map

```
CLAUDE.md                          # entry: principles + boundaries + workflow (read first)
CITATION_CONTRACT.md               # root spec: Iron Laws + data model + invariants (v0.4)
DECISIONS.md                       # locked decisions + ADR process (read before changing an approach)
ARCHITECTURE.md                    # 6 layers + agent boundaries + known gaps
citation/
  rationalization-table.md         # writer excuse/rebuttal table
  red-flags.md                     # whole-report reject conditions
  phase-gates.md                   # pipeline stage gates
  failure-handling.md              # violation handling + state machine + thresholds
  glossary.md                      # single source of terms
tests/citation_ground_truth/
  samples.md                       # 12 labeled samples (RED baseline) — in Chinese
.claude/skills/citation-builder/
  SKILL.md                         # runtime projection of the contract
```

Each doc carries a `> **Read when:**` line so agents load selectively.

## Development status

Design complete; moving to Claude Code implementation. Suggested phase order:

| Phase | Goal |
|---|---|
| P0 | skeleton + CLAUDE.md + docker-compose + health check |
| P1 | single-agent loop: Scout (with primary-fetch) → Writer → IM push of a 500-char brief |
| P2 | full pipeline + Citation Contract + Verifier (pass the ground-truth set first) |
| P3 | dual cron + ConciergeBot two-way |
| P4 | degradation paths + keyword-trigger interface + monitoring |
| P5 | cloud deploy + cross-report storage (I11) + 7-day stability |

**P1's primary-fetch is not optional** — see `ARCHITECTURE.md` Gap 1; without it the system jams at Gate 0 every day.

## Tech stack

Python 3.11+ · LangGraph · FastAPI + MCP · Postgres + Redis · **DeepSeek V4 Pro (all roles incl. judge, unlimited tokens)** · akshare · domestic sources only · IM primary WeChat / backup Feishu (see `DECISIONS.md`).

## Required plugins

This repo assumes **superpowers** (obra) and **karpathy-guidelines** are installed. At session start the agent must actively locate both; **if either is missing, stop and report an error** (see `CLAUDE.md` § 0).

## Development discipline

1. Read the relevant `CITATION_CONTRACT.md` § before touching report logic.
2. TDD: Writer/Verifier changes must pass `tests/citation_ground_truth/` first.
3. Run fresh verification before claiming "passing" (Law 5).
4. Change a locked decision only via the `DECISIONS.md` ADR process — don't quietly swap it in the implementation.
