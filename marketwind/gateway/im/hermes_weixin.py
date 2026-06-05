"""HermesWeixin: send via the installed `hermes` CLI (ADR-0001).

The real WeChat iLink send needs a per-peer context_token session and
version-pinned headers (see hermes_agent's gateway/platforms/weixin.py);
reproducing it in-process is brittle. The `hermes` CLI is the tool's public
surface and reads its own credentials from ~/.hermes/.env, so this is a thin
subprocess wrapper — no protocol duplication, no credentials in this process.

Contract: `hermes send --to <target> --json -f -` reads the body from stdin and
prints a JSON result; exit 0 = ok, 1 = delivery error, 2 = usage error.
"""
from __future__ import annotations

import json
import subprocess

from marketwind.gateway.im.base import SendResult

_TIMEOUT_S = 30


class HermesWeixin:
    def __init__(self, *, hermes_bin: str = "hermes", target: str = "weixin") -> None:
        self.hermes_bin = hermes_bin
        self.target = target

    def send(self, text: str) -> SendResult:
        try:
            proc = subprocess.run(
                [self.hermes_bin, "send", "--to", self.target, "--json", "-f", "-"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=_TIMEOUT_S,
            )
        except FileNotFoundError:
            return SendResult(ok=False, error=f"hermes binary not found: {self.hermes_bin}")
        except subprocess.TimeoutExpired:
            return SendResult(ok=False, error="hermes send timed out")
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            return SendResult(ok=False, error=err)
        try:
            result = json.loads(proc.stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return SendResult(ok=True)  # exit 0 but non-JSON output; treat as success
        if result.get("success") is True:
            return SendResult(ok=True)
        return SendResult(ok=False, error=str(result.get("error") or result))
