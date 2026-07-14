"""Unit tests for the API-key preflight's pure logic.

The live probes (check_deepseek/bocha/bark) hit real endpoints and are
`# pragma: no cover - live`; here we pin the two pure behaviors that carry the
script's value: the fail-loud exit code and the .env parser.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "check_keys.py"
_spec = importlib.util.spec_from_file_location("check_keys", _MODULE_PATH)
check_keys = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(check_keys)


def test_summarize_exit_zero_when_no_failures():
    results = [("DeepSeek", "PASS", "HTTP 200"), ("Bark", "SKIP", "unset")]
    _report, code = check_keys.summarize(results)
    assert code == 0


def test_summarize_exits_nonzero_on_any_fail():
    # Fail-loud contract: a single FAIL must fail the whole run (non-zero exit),
    # even when other keys pass — never let a bad key slip through silently.
    results = [
        ("DeepSeek", "PASS", "HTTP 200"),
        ("Bocha", "FAIL", "auth rejected (HTTP 401)"),
        ("Bark", "SKIP", "unset"),
    ]
    _report, code = check_keys.summarize(results)
    assert code == 1


def test_summarize_skip_alone_does_not_fail():
    results = [("Bark", "SKIP", "unset (optional)")]
    _report, code = check_keys.summarize(results)
    assert code == 0


def test_summarize_report_lists_every_check():
    results = [
        ("DeepSeek", "PASS", "HTTP 200"),
        ("Bocha", "FAIL", "auth rejected (HTTP 401)"),
    ]
    report, _code = check_keys.summarize(results)
    assert "DeepSeek" in report
    assert "Bocha" in report
    assert "1 CHECK(S) FAILED" in report


def test_parse_env_file_basic_and_comments():
    text = "\n".join([
        "# a comment",
        "",
        "OPENAI_API_KEY=sk-abc123",
        "  BOCHA_API_KEY = bk-xyz  ",
        'BARK_KEY="quoted-value"',
        "export OSS_BUCKET=mw-deadman",
        "# OPENAI_BASE_URL=commented-out-should-be-ignored",
    ])
    parsed = check_keys.parse_env_file(text)
    assert parsed["OPENAI_API_KEY"] == "sk-abc123"
    assert parsed["BOCHA_API_KEY"] == "bk-xyz"
    assert parsed["BARK_KEY"] == "quoted-value"
    assert parsed["OSS_BUCKET"] == "mw-deadman"
    assert "OPENAI_BASE_URL" not in parsed


def test_parse_env_file_value_may_contain_equals():
    parsed = check_keys.parse_env_file("DATABASE_URL=postgresql://u:p@h:5432/db?x=1")
    assert parsed["DATABASE_URL"] == "postgresql://u:p@h:5432/db?x=1"
