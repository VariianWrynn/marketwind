# Source-reference second message (G4.6)

> **Read when:** touching the Writer render layer or the publish path in `orchestration/runner.py`, or wondering how the reader gets clickable sources.

**Status:** complete. Branch `claude/modest-zhukovsky-b7d2a5`. Spec: `docs/superpowers/specs/2026-07-15-source-reference-second-message-design.md`. Plan: `docs/superpowers/plans/2026-07-15-source-reference-second-message.md`.

**What this delivers:** after the brief is pushed, a **second IM message** — a `—— 来源 ——` list mapping each inline `[n]` marker to its source as `[n] <domain> — <url>`. The URL is bare so WeChat/WeCom auto-linkify it into a tappable link. Pure presentation: the Verifier gate, the Writer schema, and every verified sentence's text are untouched (Law-5-neutral).

## What was done

| Module | What it does | Commit |
|---|---|---|
| `writer/render.py` | new pure `render_source_tail(footnotes, url_by_id)` → `—— 来源 ——` block of bare-URL lines; `""` if no footnotes. `render_brief` untouched | e6f784f |
| `writer/domain.py`, `writer/runner.py` | `DraftBundle` gains `reference: str`; `draft_report` builds it from `brief.footnotes` + a `source_id→url` map over the eligible pool | c934dc9 |
| `orchestration/runner.py` | `_send_soft` (non-raising failover); `run_pipeline` sends `reference` as message 2 after the report | 51db4cd |
| `tests/scheduling/*` | pass `reference=""` at the two remaining `DraftBundle` construction sites the field addition broke | cc41b30 |

## Key invariants proved here

- **Clickable, never mangled:** the reference message emits the **full URL bare** (asserted `"](" not in tail`), never markdown-wrapped, never truncated (it is its own message with its own budget — the ~4000-char IM ceiling, not the 500-char body budget).
- **No fabrication:** no article-title field exists, so entries are `domain — url` only, from data already held. No title guessing (Iron-Law-spirit safe).
- **Two-message split, not an appended tail:** the 500-char body stays a glanceable brief; **G4.7 (budget raise) was dropped as unnecessary** — no `MAX_TOTAL`/`render_brief` change.
- **Option A — loud but non-fatal (D "silent fail unwelcomed"):** if the report (message 1) is delivered but the reference (message 2) fails on **both** channels, the run stays `PUBLISHED` (the report *did* go out) and the failure is recorded in `RunOutcome.detail`, which `dispatch_job` persists to the durable ledger row. Recorded, never swallowed; a delivered report is never mislabeled as a failed run. The reference send does **not** raise (raising remains the *report's* behavior via `send_with_fallback`).
- **Idempotent:** message 2 is only reached on a fresh publish — `already_published()` short-circuits before any send, so a re-run sends neither message.
- **`render_brief` untouched:** the tail is a separate pure unit; inline `[n]` numbering (per-report, first-appearance, orphan-safe, shared-source-deduped) is unchanged.

## How to test

```bash
DATABASE_URL=... REDIS_URL=... pytest tests/writer/test_render.py tests/writer/test_draft_bundle.py tests/orchestration/test_floor_and_pipeline.py -v
```
Covers: tail format + bare-URL + number→url mapping; `DraftBundle.reference` populated/empty; two-send happy path, empty-reference single send, and option-A partial-failure (`PUBLISHED` + `detail` contains `source-reference message FAILED`).

## Out of scope / known gaps

- **Friendly outlet names** — no `domain → 中文名` map exists; `domain — url` only. If desired later, extend `scout/outlets.py` (do not fabricate).
- **G4.7 budget raise** — dropped; superseded by the two-message split.
- Title extraction / page `<title>` fetch — a correctness risk, deliberately not built.
