"""Test that assemble() preserves category/methodology across the alias-to-uuid remap."""

import json
from datetime import date

from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.writer import assemble


def _pool():
    q = PooledQuote(quote_id="uuid-q", text="日赚3.6亿", is_quantitative=True,
                    quote_type="data", attached_primary_url="https://cninfo.com.cn/x",
                    span_start=0, span_end=5)
    return [PooledSource(source_id="uuid-s", url="https://cninfo.com.cn/x",
                         domain="cninfo.com.cn", is_primary=True, quotes=[q],
                         raw_content="日赚3.6亿")]


async def test_assemble_preserves_category_and_methodology():
    content = json.dumps({
        "claims": [{"id": "c-001", "statement": "长鑫日赚3.6亿元。",
                    "quote_ids": ["q1"], "category": "derived_metric",
                    "methodology": "按净利润计"}],
        "sentences": [{"sentence": "长鑫日赚3.6亿元。", "claim_ids": ["c-001"],
                       "source_ids": ["s1"], "sentence_type": "factual"}],
    })

    async def stub_call(_messages):
        return content

    out = await assemble(_pool(), call=stub_call, session_date=date(2026, 7, 23))
    assert out.claims[0].category == "derived_metric"
    assert out.claims[0].methodology == "按净利润计"
    assert out.claims[0].quote_ids == ["uuid-q"]  # alias remapped to real uuid
