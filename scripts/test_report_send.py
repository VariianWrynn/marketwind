#!/usr/bin/env python3
"""End-to-end test report send — scout → writer → verifier → render → WeChat.

Reusable test script: generates a report from the current DB pool (or a
synthetic pool if the DB is empty), runs it through the full pipeline,
and sends the rendered brief to WeChat via HermesWeixin.

Usage:
    # From host (hermes available):
    PYTHONPATH=. python scripts/test_report_send.py

    # From scheduler container:
    docker compose exec scheduler python scripts/test_report_send.py

    # With synthetic pool (no DB needed):
    PYTHONPATH=. python scripts/test_report_send.py --synthetic

    # Dry run (print but don't send):
    PYTHONPATH=. python scripts/test_report_send.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on path
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from marketwind.writer.domain import (
    DraftClaim,
    DraftSentence,
    PooledQuote,
    PooledSource,
    WriterOutput,
)
from marketwind.writer.writer import assemble
from marketwind.writer.render import render_brief, render_source_tail
from marketwind.verifier.verifier import verify
from marketwind.gateway.im.hermes_weixin import HermesWeixin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("test_report_send")

_CST = timezone(offset=timedelta(hours=8))


# ---------------------------------------------------------------------------
# Synthetic pool — used when --synthetic or DB is empty
# ---------------------------------------------------------------------------

def _build_synthetic_pool() -> list[PooledSource]:
    """A realistic pool with 3 sources covering index + earnings + disclosure."""
    # Raw content strings — spans must satisfy raw_content[start:end] == text (RF-3)
    raw1 = "科创50指数5月27日收涨1.82%，报1023.45点，成交额287.3亿元。成分股中，中芯国际涨5.23%，海光信息涨3.17%。"
    q1_text = "科创50指数5月27日收涨1.82%，报1023.45点，成交额287.3亿元"
    q2_text = "中芯国际涨5.23%"
    raw2 = "中芯国际2026年一季度实现营业收入176.17亿元，同比增长26.5%；归母净利润13.61亿元，同比增长41.2%。"
    q3_text = "中芯国际2026年一季度实现营业收入176.17亿元，同比增长26.5%"
    q4_text = "归母净利润13.61亿元，同比增长41.2%"
    raw3 = "中芯国际集成电路制造有限公司2026年第一季度报告：营业收入176.17亿元，同比增长26.5%；归属于上市公司股东的净利润13.61亿元，同比增长41.2%。"
    q5_text = "营业收入176.17亿元，同比增长26.5%"

    # Verify spans match (RF-3 invariant)
    assert raw1[0:len(q1_text)] == q1_text
    assert raw1[raw1.index(q2_text):raw1.index(q2_text)+len(q2_text)] == q2_text
    assert raw2[0:len(q3_text)] == q3_text
    assert raw2[raw2.index(q4_text):raw2.index(q4_text)+len(q4_text)] == q4_text
    assert raw3[raw3.index(q5_text):raw3.index(q5_text)+len(q5_text)] == q5_text

    return [
        PooledSource(
            source_id="s-test-001",
            url="https://finance.sina.com.cn/stock/2026-05-28/doc-star50.shtml",
            domain="finance.sina.com.cn",
            is_primary=False,
            quotes=[
                PooledQuote(
                    quote_id="q-test-001",
                    text=q1_text,
                    is_quantitative=True,
                    quote_type="factual",
                    attached_primary_url="https://finance.sina.com.cn/stock/2026-05-28/doc-star50.shtml",
                    span_start=0,
                    span_end=len(q1_text),
                ),
                PooledQuote(
                    quote_id="q-test-002",
                    text=q2_text,
                    is_quantitative=True,
                    quote_type="factual",
                    attached_primary_url="https://finance.sina.com.cn/stock/2026-05-28/doc-star50.shtml",
                    span_start=raw1.index(q2_text),
                    span_end=raw1.index(q2_text) + len(q2_text),
                ),
            ],
            raw_content=raw1,
        ),
        PooledSource(
            source_id="s-test-002",
            url="https://stcn.com/article/detail/star-earnings.html",
            domain="stcn.com",
            is_primary=False,
            quotes=[
                PooledQuote(
                    quote_id="q-test-003",
                    text=q3_text,
                    is_quantitative=True,
                    quote_type="data",
                    attached_primary_url="https://stcn.com/article/detail/star-earnings.html",
                    span_start=0,
                    span_end=len(q3_text),
                ),
                PooledQuote(
                    quote_id="q-test-004",
                    text=q4_text,
                    is_quantitative=True,
                    quote_type="data",
                    attached_primary_url="https://stcn.com/article/detail/star-earnings.html",
                    span_start=raw2.index(q4_text),
                    span_end=raw2.index(q4_text) + len(q4_text),
                ),
            ],
            raw_content=raw2,
        ),
        PooledSource(
            source_id="s-test-003",
            url="https://www.cninfo.com.cn/disclosure/688981-2026q1",
            domain="cninfo.com.cn",
            is_primary=True,
            quotes=[
                PooledQuote(
                    quote_id="q-test-005",
                    text=q5_text,
                    is_quantitative=True,
                    quote_type="data",
                    attached_primary_url="https://www.cninfo.com.cn/disclosure/688981-2026q1",
                    span_start=raw3.index(q5_text),
                    span_end=raw3.index(q5_text) + len(q5_text),
                ),
            ],
            raw_content=raw3,
        ),
    ]


# ---------------------------------------------------------------------------
# DB pool loader
# ---------------------------------------------------------------------------

async def _load_pool_from_db() -> list[PooledSource] | None:
    """Try to load pool from DB. Returns None if empty or unavailable."""
    try:
        import asyncpg
        from marketwind.config import settings
        from marketwind.storage.repo import load_pool
        # Use localhost for host-side runs; container uses 'postgres' hostname
        db_url = settings.database_url.replace("postgres:5432", "localhost:5432")
        conn = await asyncpg.connect(db_url)
        try:
            pool = await load_pool(conn)
            return pool if pool else None
        finally:
            await conn.close()
    except Exception as e:
        log.warning(f"DB pool load failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Writer call (DeepSeek)
# ---------------------------------------------------------------------------

async def _call_deepseek(messages: list[dict]) -> str:
    """Call DeepSeek API for the Writer."""
    import httpx
    from marketwind.config import settings

    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    body = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": 16000,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    if not content:
        raise RuntimeError("empty model response")
    return content


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    pool: list[PooledSource],
    *,
    session_date: date,
    dry_run: bool = False,
) -> tuple[str, str, str]:
    """Run writer → verifier → render. Returns (body, reference, verify_detail)."""

    # 1. Writer
    log.info("Running Writer (DeepSeek)...")
    from marketwind.writer.prompt import build_writer_prompt, alias_pool
    from marketwind.writer.schema import parse_and_validate

    messages = build_writer_prompt(pool, session_date=session_date)
    raw_json = await _call_deepseek(messages)
    log.info(f"Raw model output ({len(raw_json)} chars): {raw_json[:500]}")

    # Validate + remap aliases
    rows, q_map, s_map = alias_pool(pool)
    from marketwind.writer.schema import SchemaViolation
    try:
        validated = parse_and_validate(raw_json, set(q_map), set(s_map))
    except SchemaViolation as e:
        log.warning(f"Schema violation: {e}")
        log.warning("Raw output (first 500 chars):")
        log.warning(raw_json[:500])
        # Create empty output as fallback
        from marketwind.writer.domain import WriterOutput as _WO
        return "⚠️ Writer 输出未通过 schema 验证", "", f"SCHEMA FAIL: {e}"
    from marketwind.writer.domain import DraftClaim, DraftSentence
    remapped_claims = [
        DraftClaim(local_id=c.local_id, statement=c.statement,
                   quote_ids=[q_map[a] for a in c.quote_ids],
                   category=c.category, methodology=c.methodology,
                   time_window=getattr(c, 'time_window', None))
        for c in validated.claims
    ]
    remapped_sentences = [
        DraftSentence(sentence=s.sentence, claim_ids=list(s.claim_ids),
                      source_ids=[s_map[a] for a in s.source_ids],
                      sentence_type=s.sentence_type)
        for s in validated.sentences
    ]
    output = WriterOutput(claims=remapped_claims, sentences=remapped_sentences)
    log.info(f"Writer output: {len(output.claims)} claims, {len(output.sentences)} sentences")

    # 2. Verifier
    log.info("Running Verifier...")
    result = await verify(output, pool, judge=_stub_judge)
    if not result.passed:
        checks = sorted(set(v.check for v in result.violations))
        detail = f"VERIFY FAIL: {len(result.violations)} violations ({', '.join(checks)})"
        log.warning(detail)
        for v in result.violations:
            log.warning(f"  {v.check}: {v.locus} — {v.detail}")
        # Still render and send with a failure notice
    else:
        detail = "VERIFY PASS"
        log.info(detail)

    # 4. Render
    official_ids = set()  # no cninfo trace in test mode
    brief = render_brief(output, max_chars=500, official_ids=official_ids)
    url_by_id = {s.source_id: s.url for s in pool}
    reference = render_source_tail(brief.footnotes, url_by_id)

    body = brief.body
    if not result.passed:
        body = f"⚠️ 验证未通过（{len(result.violations)} 项）\n\n{body}"

    return body, reference, detail


async def _stub_judge(prompt: str) -> str:
    """Stub judge — returns no violations (fail closed for real use, but
    for test sends we want to see the rendered output)."""
    return '{"violations": []}'


async def main():
    parser = argparse.ArgumentParser(description="Test report send to WeChat")
    parser.add_argument("--synthetic", action="store_true",
                        help="use synthetic pool instead of DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="print report but don't send")
    args = parser.parse_args()

    # 1. Load pool
    if args.synthetic:
        log.info("Using synthetic pool")
        pool = _build_synthetic_pool()
    else:
        log.info("Loading pool from DB...")
        pool = await _load_pool_from_db()
        if not pool:
            log.warning("DB pool empty, falling back to synthetic")
            pool = _build_synthetic_pool()

    log.info(f"Pool: {len(pool)} sources, {sum(len(s.quotes) for s in pool)} quotes")

    # 2. Run pipeline
    today = datetime.now(_CST).date()
    body, reference, verify_detail = await run_pipeline(pool, session_date=today)

    # 3. Compose full message
    header = f"📊 MarketWind 测试报告 ({today})\n"
    full_message = f"{header}\n{body}"
    if reference:
        full_message += f"\n\n{reference}"
    full_message += f"\n\n---\n{verify_detail}"

    # 4. Print
    print("\n" + "=" * 60)
    print(full_message)
    print("=" * 60 + "\n")

    # 5. Send
    if args.dry_run:
        log.info("Dry run — not sending")
        return

    log.info("Sending via HermesWeixin...")
    ch = HermesWeixin()
    result = ch.send(full_message)
    if result.ok:
        log.info("✅ Message sent successfully")
    else:
        log.error(f"❌ Send failed: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
