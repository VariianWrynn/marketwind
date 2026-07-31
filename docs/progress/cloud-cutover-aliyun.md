# Cloud cutover (Aliyun ECS) — image/delivery gaps found on the real box

> **Read when:** deploying to (or debugging) the Aliyun report node, changing the `Dockerfile`, the prod compose override, or the in-container hermes wiring; or reconciling the repo with fixes that currently live only on the box.

**Status:** in progress, 2026-07-24. The stack runs on the Aliyun ECS report node and pushed a real (DEV-labelled) report to WeChat — see `cloud-smoke-stage2.md`. This is the **Stage 4 cloud cutover** that `deployment-live-smoke.md` deferred as "mechanical follow-up after the node is purchased." It was **not** mechanical: running the image on a real China-network box surfaced three image-packaging gaps and one delivery-path gap, all of the same class (the container was missing something the code assumes at runtime).

> **⚠ The fixes ARE on `master` — mind your branch.** Every fix below is committed on `master`: the `Dockerfile` (`COPY citation`, `pip install`, Playwright + npmmirror + Aliyun apt mirror — commits `c35c2c1`, `fd6500e`, `d371883`, `ef03fed`) and the hermes compose / `.env.example` wiring (`8c24ef5`), now pushed to `origin/master`. **Caveat (obvious-fail — do not let this rot):** feature branches cut before this work (e.g. `fix/pr-10-…`) and any stale checkout still carry the **original** three-`COPY` / `--no-cache-dir` Dockerfile with no Playwright and no `citation/`. **Rebuild the report node from `master`, not from an old branch, or these fixes silently vanish.** This note is the record of what each fix is and why.

## What was found & fixed, by gap

| Gap | Symptom on the box | Root cause | Fix (where) |
|---|---|---|---|
| Migrations never applied | `scheduler` crash-loop: `UndefinedTableError: relation "run_ledger" does not exist` | No container runs `migrate` automatically (by design — idempotent, owner-run) | Run once after first `up`: `docker compose … exec app python -m marketwind.storage.migrate`. Already in `deploy/report-node/README.md` §9 — operational, no code change. |
| Playwright browser missing | Stage-1 crash: `Executable doesn't exist at …/chrome-headless-shell`; `playwright: command not found` | Scout's `gather_live` launches headless Chromium; the pip package ships **no** browser binary | `Dockerfile`: `RUN playwright install --with-deps chromium`. China network → browser from **npmmirror** (`ENV PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`); `--with-deps` apt step re-pointed to **Aliyun** Debian mirror (it was crawling against `deb.debian.org`). |
| `citation/` dir missing | Stage-2 crash: `FileNotFoundError: '/app/citation/rationalization-table.md'` at `writer/prompt.py:98` | Image `COPY`s only `marketwind/` + `migrations/`; the Writer reads `citation/rationalization-table.md` at runtime | `Dockerfile`: `COPY citation ./citation` (ship the whole small companion dir — the Verifier loads other `citation/` files too). |
| hermes not on image PATH | `--send-real` could not reach WeChat; `hermes` not found in container | hermes (WeChat delivery, ADR-0001) is **git-installed** in a **uv-managed py3.11 venv** at `/root/.hermes/hermes-agent/venv/`, whose interpreter is symlinked **outside** `~/.hermes` to `/root/.local/share/uv/python/…`. Not pip-installable (not on PyPI). | **Zero image change.** Prod compose mounts the uv interpreter dir into `scheduler` (`${HERMES_UV_PYTHON_DIR}:…:ro`); `.env` sets `HERMES_BIN=/root/.hermes/hermes-agent/venv/bin/hermes`. `~/.hermes` (venv + creds) was already mounted by base compose. Verified: real send landed on the owner's phone. |

Supporting China-network mirrors already in place / used: PyPI = Tsinghua (`PIP_INDEX_URL`), Docker registry = daocloud / 1ms.run.

## Key facts

- **All four gaps are "the container lacks a runtime dependency the code assumes."** Migrations (DB state), Chromium (crawler), `citation/` (Writer prompt), hermes interpreter (delivery). When adding any new runtime file-read or external binary, check it is packaged/mounted — this class of gap fails loud only *at the moment the code path runs*, which on this node can be mid-report.
- **hermes stays out of the image on purpose.** Reusing the host's git-installed venv via bind-mounts (ADR-0001) is a zero-image-change path; the only fragility is the uv interpreter living outside `~/.hermes`, which the extra mount covers. Do not try to `pip install hermes` — it is not on PyPI.
- **Freshness guard is working, not broken.** Stage-2 off-hours reruns hit `skipped_stale: past ceiling 10:00 CST` — correct behavior. `--force-fresh` is the designed off-hours-rehearsal override; the verifier gate still runs under it. Never loosen the ceiling to force a run.
- **Diagnosis discipline paid off.** The initial "scheduler still crash-looping" was a **stale log** (crash timestamp predated the migration); proven via `docker inspect` restart-count = 0 (unchanged `startedAt`) + `\dt` showing `run_ledger` exists — not by guessing.

## Open — must not be dropped

- **Box fixes are committed & pushed to `master`** (`Dockerfile`, prod compose uv-interpreter mount, `.env.example` `HERMES_BIN`/`HERMES_UV_PYTHON_DIR`). Remaining risk is only branch hygiene — rebuild from `master` (see warning above).
- **OSS backup** — attach the ECS RAM role, create bucket `mw-deadman`, add the 14-day `backups/pg/` lifecycle rule (owner console work; the backup sidecar fails loud until then).
- **Dead-man watcher (`deploy/deadman-fc/`)** — the out-of-process silent-miss closer; ping URLs still unset in `.env`.
- **`pip install` vs `--no-cache-dir`** — dropping `--no-cache-dir` speeds rebuilds but bloats the layer; only matters when the install layer is re-run. Owner reverted it; note for whoever re-commits the Dockerfile.
