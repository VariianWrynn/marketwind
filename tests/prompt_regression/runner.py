#!/usr/bin/env python3
"""Prompt regression runner — scores a Writer prompt revision against a baseline.

Calls DeepSeek (D-26: deepseek-v4-pro) on a frozen pool fixture, parses the
output through schema validation, scores it against assertions, and compares
against the baseline. Exit 0 = all scores ≥ baseline. Exit 1 = regression.

Requires OPENAI_API_KEY and OPENAI_BASE_URL in env (or .env file).
Exits non-zero with a clear message if the key is absent — never skips silently.

Usage:
    make eval-prompt
    python tests/prompt_regression/runner.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

_DIR = Path(__file__).parent
_BASELINE_PATH = _DIR / "baseline.json"

_FILLER = re.compile(r"据报道|业内人士|市场认为|普遍预期|通常来说|分析人士|知情人士|接近.{0,8}的人士|有消息称")
_FIRST_PERSON = re.compile(r"系统认为|分析显示|综合判断|经测算|研究表明")
_PRONOUN_SUBJECT = re.compile(r"^该股|^该公司|^该指数|^它|^其")

_VALID_CATEGORIES = frozenset({
    "quantitative", "temporal", "comparative", "attribution", "causal",
    "quoted_inference", "freshness", "derived_metric", "correction",
})


def _load_dotenv() -> None:
    """Load .env from the project root if present (minimal, no dependency)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def _check_env() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) or exit with a clear error."""
    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    base_url = os.environ.get("OPENAI_BASE_URL") or ""
    model = os.environ.get("LLM_MODEL") or "deepseek-v4-pro"
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY not set. "
            "Prompt regression requires a live DeepSeek API key.\n"
            "Set it via env or .env file: "
            "export OPENAI_API_KEY=sk-...",
            file=sys.stderr,
        )
        sys.exit(1)
    if not base_url:
        print(
            "ERROR: OPENAI_BASE_URL not set. "
            "Set it via env or .env file: "
            "export OPENAI_BASE_URL=https://api.deepseek.com",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key, base_url, model


def _load_pool_fixture(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_pool(raw_sources: list[dict]):
    """Build PooledSource list from the fixture JSON."""
    from marketwind.writer.domain import PooledQuote, PooledSource

    sources = []
    for s in raw_sources:
        quotes = [
            PooledQuote(
                quote_id=q["quote_id"],
                text=q["text"],
                is_quantitative=q["is_quantitative"],
                quote_type=q.get("quote_type", "factual"),
                attached_primary_url=q.get("attached_primary_url"),
                span_start=q.get("span_start", 0),
                span_end=q.get("span_end", len(q["text"])),
            )
            for q in s["quotes"]
        ]
        sources.append(PooledSource(
            source_id=s["source_id"],
            url=s["url"],
            domain=s["domain"],
            is_primary=s["is_primary"],
            quotes=quotes,
            raw_content=s["raw_content"],
        ))
    return sources


async def _call_model(messages: list[dict], *, api_key: str, base_url: str, model: str) -> str:
    """Call DeepSeek and return the assistant message content."""
    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": 16000,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("chat completion has no choices")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("chat completion message has empty content")
    return content


def _score_output(raw: str, pool_quote_ids: set[str], pool_source_ids: set[str]) -> dict[str, int]:
    """Score the Writer output against assertions. Returns a dict of score_name → 0/1."""
    scores: dict[str, int] = {
        "valid_json": 0,
        "claims_count_min": 0,
        "no_invalid_category": 0,
        "no_filler": 0,
        "no_first_person": 0,
        "self_contained_subjects": 0,
        "schema_clean": 0,
    }

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return scores
    scores["valid_json"] = 1

    if not isinstance(data, dict):
        return scores

    claims = data.get("claims", [])
    sentences = data.get("sentences", [])
    if not isinstance(claims, list) or not isinstance(sentences, list):
        return scores

    if len(claims) >= 1:
        scores["claims_count_min"] = 1

    invalid_cats = [c for c in claims if c.get("category", "quantitative") not in _VALID_CATEGORIES]
    if not invalid_cats:
        scores["no_invalid_category"] = 1

    all_text = " ".join(
        [c.get("statement", "") for c in claims]
        + [s.get("sentence", "") for s in sentences]
    )
    if not _FILLER.search(all_text):
        scores["no_filler"] = 1
    if not _FIRST_PERSON.search(all_text):
        scores["no_first_person"] = 1

    pronoun_violations = [
        c for c in claims
        if _PRONOUN_SUBJECT.match(c.get("statement", ""))
    ]
    if not pronoun_violations:
        scores["self_contained_subjects"] = 1

    from marketwind.writer.schema import parse_and_validate, SchemaViolation
    try:
        parse_and_validate(raw, pool_quote_ids, pool_source_ids)
        scores["schema_clean"] = 1
    except SchemaViolation:
        pass

    return scores


async def main() -> int:
    api_key, base_url, model = _check_env()

    with open(_BASELINE_PATH, encoding="utf-8") as f:
        baseline = json.load(f)

    fixture_name = baseline.get("fixture", "pool_fixture.json")
    fixture_path = _DIR / fixture_name
    if not fixture_path.exists():
        print(f"ERROR: pool fixture not found: {fixture_path}", file=sys.stderr)
        return 1

    raw_sources = _load_pool_fixture(fixture_path)
    pool = _build_pool(raw_sources)

    pool_quote_ids: set[str] = set()
    pool_source_ids: set[str] = set()
    for s in pool:
        pool_source_ids.add(s.source_id)
        for q in s.quotes:
            pool_quote_ids.add(q.quote_id)

    from marketwind.writer.prompt import build_writer_prompt
    messages = build_writer_prompt(pool, session_date=date(2026, 5, 27))

    print(f"Calling {model} at {base_url} ...")
    try:
        raw_output = await _call_model(messages, api_key=api_key, base_url=base_url, model=model)
    except Exception as exc:
        print(f"ERROR: model call failed: {exc}", file=sys.stderr)
        return 1

    scores = _score_output(raw_output, pool_quote_ids, pool_source_ids)
    min_scores = baseline.get("min_scores", {})

    print(f"\nPrompt regression scores (baseline {baseline.get('note', '?')}):")
    regressions = 0
    for key, expected in sorted(min_scores.items()):
        actual = scores.get(key, 0)
        status = "PASS" if actual >= expected else "FAIL"
        if actual < expected:
            regressions += 1
        print(f"  [{status}] {key}: {actual} (min {expected})")

    total = len(min_scores)
    print(f"\n{total - regressions}/{total} assertions passed")

    if regressions:
        print(f"\nREGRESSION: {regressions} assertion(s) below baseline")
        print("The prompt template has regressed — fix before merging.")
        return 1

    print("OK: all prompt regression assertions pass")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
