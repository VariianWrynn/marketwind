#!/usr/bin/env python3
"""Preflight: verify the external API keys in .env actually authenticate.

Run on the box AFTER populating .env and BEFORE `docker compose up` — it catches
a bad/expired/misspelled key in seconds instead of after a full build + a silent
failed report:

    python3 deploy/report-node/check_keys.py            # reads ./.env
    python3 deploy/report-node/check_keys.py /path/.env # explicit .env path

Stdlib-only (urllib) so it runs on a bare host with just python3 — no venv, no
container, no project deps. It hits the same endpoints and auth-header shape the
app clients use (marketwind/writer/client.py, marketwind/scout/discover.py).

Checks:
  - DeepSeek  OPENAI_API_KEY + OPENAI_BASE_URL   -> minimal chat completion
  - Bocha     BOCHA_API_KEY                      -> minimal web search
  - Bark      BARK_BASE_URL + BARK_KEY           -> test push (SKIP if unset)

Fails LOUD (project value: "silent fail strongly unwelcomed"): prints a PASS /
FAIL / SKIP table and exits non-zero if ANY configured key fails. Bark is
optional — unset = SKIP, never FAIL.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

# (name, status, detail)
Result = tuple[str, str, str]


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env file body.

    Skips blank lines and `#` comments; strips an optional `export ` prefix and
    surrounding quotes. First `=` splits key from value (values may contain `=`).
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env(env_path: Path) -> dict[str, str]:
    """Merge .env file values over the process environment (file wins)."""
    merged = dict(os.environ)
    if env_path.is_file():
        merged.update(parse_env_file(env_path.read_text(encoding="utf-8")))
    return merged


def summarize(results: list[Result]) -> tuple[str, int]:
    """Render the PASS/FAIL/SKIP table and compute the exit code.

    Exit code is 1 if ANY result is FAIL, else 0 (SKIP never fails the run).
    """
    width = max((len(name) for name, _, _ in results), default=0)
    lines = [f"  {name.ljust(width)}  {status}  {detail}".rstrip()
             for name, status, detail in results]
    failed = sum(1 for _, status, _ in results if status == FAIL)
    passed = sum(1 for _, status, _ in results if status == PASS)
    skipped = sum(1 for _, status, _ in results if status == SKIP)
    lines.append("")
    verdict = "ALL CHECKS PASSED" if failed == 0 else f"{failed} CHECK(S) FAILED"
    lines.append(f"{verdict}  (pass={passed} fail={failed} skip={skipped})")
    return "\n".join(lines), (1 if failed else 0)


def _classify_http(err: urllib.error.HTTPError) -> str:
    if err.code in (401, 403):
        return f"{FAIL}||auth rejected (HTTP {err.code}) — key wrong/expired"
    return f"{FAIL}||HTTP {err.code}"


def _probe(request: urllib.request.Request) -> str:  # pragma: no cover - live
    """Return 'PASS||detail' or 'FAIL||detail' for a live request."""
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            return f"{PASS}||HTTP {resp.status}"
    except urllib.error.HTTPError as err:
        return _classify_http(err)
    except urllib.error.URLError as err:
        return f"{FAIL}||connection error: {err.reason}"
    except Exception as err:  # noqa: BLE001 - preflight must never crash mid-table
        return f"{FAIL}||{type(err).__name__}: {err}"


def _result(name: str, probe_out: str) -> Result:
    status, _, detail = probe_out.partition("||")
    return (name, status, detail)


def check_deepseek(env: dict[str, str]) -> Result:  # pragma: no cover - live
    key = env.get("OPENAI_API_KEY", "")
    base = env.get("OPENAI_BASE_URL", "").rstrip("/")
    if not key:
        return ("DeepSeek", FAIL, "OPENAI_API_KEY unset")
    if not base:
        return ("DeepSeek", FAIL, "OPENAI_BASE_URL unset")
    body = json.dumps({
        "model": env.get("LLM_MODEL", "deepseek-v4-pro"),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    return _result("DeepSeek", _probe(req))


def check_bocha(env: dict[str, str]) -> Result:  # pragma: no cover - live
    key = env.get("BOCHA_API_KEY", "")
    if not key:
        return ("Bocha", FAIL, "BOCHA_API_KEY unset")
    body = json.dumps({"query": "测试", "count": 1}).encode()
    req = urllib.request.Request(
        "https://api.bochaai.com/v1/web-search",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    return _result("Bocha", _probe(req))


def check_bark(env: dict[str, str]) -> Result:  # pragma: no cover - live
    base = env.get("BARK_BASE_URL", "").rstrip("/")
    key = env.get("BARK_KEY", "")
    if not base or not key:
        return ("Bark", SKIP, "unset (optional — backup/watcher alerts disabled)")
    req = urllib.request.Request(
        f"{base}/{key}/MarketWind%20key%20check", method="GET"
    )
    return _result("Bark", _probe(req))


def main(argv: list[str]) -> int:  # pragma: no cover - live
    env_path = Path(argv[1]) if len(argv) > 1 else Path.cwd() / ".env"
    env = load_env(env_path)
    print(f"Checking API keys (source: {env_path if env_path.is_file() else 'process env only'})\n")
    results = [check_deepseek(env), check_bocha(env), check_bark(env)]
    report, code = summarize(results)
    print(report)
    return code


if __name__ == "__main__":  # pragma: no cover - live
    sys.exit(main(sys.argv))
