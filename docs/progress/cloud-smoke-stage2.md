# Cloud smoke Stage 2 — first report pushed from the ECS node, content flags open

> **Read when:** deciding whether to flip `REPORT_DEV_LABEL=false`, or investigating why a rendered report cites few sources / drifts off the 科创50 scope. Runbook: `docs/runbooks/go-live-smoke.md`. Infra context: `cloud-cutover-aliyun.md`.

**Status:** Stage 1 PASS, Stage 2 plumbing PASS / **content NOT accepted**, 2026-07-24. Run on the **Aliyun ECS node** (the runbook was written for local Docker Desktop; the cloud box is the same compose stack). **DEV label kept ON** — the pipeline is trustworthy, the report content is not yet.

**What happened:** the first end-to-end autonomous report generated on the cloud node reached a real WeChat push with the `【DEV / UNVERIFIED — 非正式报告】` prefix, and landed on the owner's phone. Getting there cleared the Stage-4 image gaps (see `cloud-cutover-aliyun.md`). The owner then eyeballed the report — the runbook's acceptance signal — and it showed content defects that must be understood before any label flip.

## Stages run

| Stage | Command | Outcome |
|---|---|---|
| 1 — floor | `--floor-only` | **PASS**, strongly: `grounded=470 primary=10 outlets=20 passed=True` (zero DeepSeek tokens). |
| 2 — real push | `--send-real --force-fresh` | **Plumbing PASS**: draft → verifier gate (Law 5) → commit → real `HermesWeixin` push with DEV prefix → **owner confirmed receipt**. Two blockers cleared en route: freshness ceiling (used `--force-fresh`, off-hours rehearsal) and the missing `citation/` dir (see cutover note). |
| 3 — daemon | — | Not yet run (self-fire + `docker restart` durability). |

## Content findings (owner eyeball — the acceptance signal)

The delivered report (2026-07-22 recap) read as a competent A-share market summary but is **not** an acceptable 科创50 morning report:

1. **Single-source render.** Every sentence cited `[1]` — one source — despite the Stage-1 floor reporting `outlets=20`. The floor counts diversity in the **gathered pool**, not what the render actually cites; a 20-outlet gather collapsing to a one-source render is the **highest-value thread to investigate** and the one closest to the Iron Laws (source traceability). Open question: real thinness in claim-mapping, or a render/display artifact?
2. **Scope drift.** The report centered on 上证指数 / 创业板 / broad sectors, and the one named stock — 中国巨石 (`sh600176`) — is a Shanghai **main-board** stock, not a 科创板 (688xxx) constituent. A STAR50 report should center on the 科创50 index and 688-prefixed names. Market context is fine; the center of gravity was off-target.
3. **Date (benign).** Covered 2026-07-22 while "today" was 07-24 — expected for a `--force-fresh` off-hours rehearsal, which anchors to the most recent trading day. Noted so it isn't mistaken for live drift.

## Decision — recorded

- **`REPORT_DEV_LABEL` stays ON.** Per the runbook, flipping to `false` is an explicit, recorded owner decision made **only** after eyeballing a trustworthy report. Findings #1 and #2 are exactly what the DEV label exists to gate. The verifier gate was never loosened; the DEV prefix is a label, not a check.
- **Plumbing is trustworthy; content is not yet.** The push path (draft → Law-5 gate → commit → WeChat) is proven end-to-end on the cloud node.

## Open — must not be dropped

- **Investigate the single-source render (#1)** — trace why claim-mapping/render collapses to one source when the floor shows 20 outlets. Start at the Writer render + claim→source binding.
- **科创50 scope (#2)** — confirm whether Scout gather + Writer selection are actually STAR50-centered or defaulting to broad-market recap.
- **Stage 3** — daemon self-fire (temp cron ~2 min ahead) + `docker restart` durability (no duplicate publish for an already-published day).
- **Only after #1/#2 resolve and a clean report is eyeballed** may the owner flip `REPORT_DEV_LABEL=false`.
