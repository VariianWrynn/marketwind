#!/usr/bin/env python3
"""Preflight: verify the external API keys in .env actually authenticate.

Run on the box AFTER populating .env and BEFORE `docker compose up` -- it catches
a bad/expired/misspelled key in seconds instead of after a full build and a
silent failed report:

    python3 deploy/report-node/check_keys.py            # reads ./.env
    python3 deploy/report-node/check_keys.py /path/.env # explicit .env path

Stdlib-only (urllib), no type hints, no __future__ -- runs on python3 >= 3.6 on
a bare host (no venv, no deps). It hits the SAME endpoints and auth-header shape
the app uses: DeepSeek POST {base}/chat/completions (marketwind/writer/client.py)
and Bocha POST https://api.bochaai.com/v1/web-search (marketwind/scout/discover.py).

Fails LOUD: prints a PASS / FAIL / SKIP table and exits non-zero if ANY
configured key fails. Bark is optional -- unset = SKIP, never FAIL.
"""

import json
import os
import sys

try:                                # py3
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:                 # py2 fallback
    from urllib2 import Request, urlopen, HTTPError, URLError

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def parse_env_file(text):
    """Parse KEY=VALUE lines from a .env body -> dict.

    Skips blanks and '#' comments; drops an optional 'export ' prefix and
    surrounding quotes; first '=' splits key/value (values may contain '=').
    """
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env(path):
    """Merge .env file values over the process environment (file wins)."""
    merged = dict(os.environ)
    if os.path.isfile(path):
        with open(path, "r") as fh:
            merged.update(parse_env_file(fh.read()))
    return merged


def summarize(results):
    """Render the PASS/FAIL/SKIP table; return (text, exit_code).

    exit_code is 1 if ANY result is FAIL, else 0 (SKIP never fails the run).
    """
    width = max([len(name) for name, _, _ in results] or [0])
    lines = []
    for name, status, detail in results:
        lines.append(("  %s  %s  %s" % (name.ljust(width), status, detail)).rstrip())
    failed = len([1 for _, s, _ in results if s == FAIL])
    passed = len([1 for _, s, _ in results if s == PASS])
    skipped = len([1 for _, s, _ in results if s == SKIP])
    lines.append("")
    verdict = "ALL CHECKS PASSED" if failed == 0 else "%d CHECK(S) FAILED" % failed
    lines.append("%s  (pass=%d fail=%d skip=%d)" % (verdict, passed, failed, skipped))
    return "\n".join(lines), (1 if failed else 0)


def _probe(request):
    """Fire a live request -> (status, detail). 200 = PASS; 401/403 = bad key."""
    try:
        resp = urlopen(request, timeout=20)
        code = getattr(resp, "status", None) or resp.getcode()
        resp.close()
        return (PASS, "HTTP %s" % code)
    except HTTPError as err:
        if err.code in (401, 403):
            return (FAIL, "auth rejected (HTTP %d) -- key wrong/expired" % err.code)
        return (FAIL, "HTTP %d" % err.code)
    except URLError as err:
        return (FAIL, "connection error: %s" % err.reason)
    except Exception as err:  # preflight must never crash mid-table
        return (FAIL, "%s: %s" % (type(err).__name__, err))


def check_deepseek(env):
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
    }).encode("utf-8")
    req = Request(base + "/chat/completions", data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    status, detail = _probe(req)
    return ("DeepSeek", status, detail)


def check_bocha(env):
    key = env.get("BOCHA_API_KEY", "")
    if not key:
        return ("Bocha", FAIL, "BOCHA_API_KEY unset")
    body = json.dumps({"query": "test", "count": 1}).encode("utf-8")
    req = Request("https://api.bochaai.com/v1/web-search", data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    status, detail = _probe(req)
    return ("Bocha", status, detail)


def check_bark(env):
    base = env.get("BARK_BASE_URL", "").rstrip("/")
    key = env.get("BARK_KEY", "")
    if not base or not key:
        return ("Bark", SKIP, "unset (optional -- backup/watcher alerts disabled)")
    req = Request(base + "/" + key + "/MarketWind%20key%20check")  # GET
    status, detail = _probe(req)
    return ("Bark", status, detail)


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.join(os.getcwd(), ".env")
    env = load_env(path)
    src = path if os.path.isfile(path) else "process env only"
    sys.stdout.write("Checking API keys (source: %s)\n\n" % src)
    results = [check_deepseek(env), check_bocha(env), check_bark(env)]
    report, code = summarize(results)
    sys.stdout.write(report + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
