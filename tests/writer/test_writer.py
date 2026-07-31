import json
from datetime import date

from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.writer import assemble

# Real ids that are clearly NOT aliases (not q1/q2/s1)
_RAW_A = "科创50收涨0.36%。市场情绪偏谨慎。"
POOL = [
    PooledSource("SRC-A", "https://m.cls.cn/a/1", "m.cls.cn", False, [
        PooledQuote("QUO-1", "科创50收涨0.36%。", True, "data", "https://cninfo.com.cn/x",
                    span_start=0, span_end=len("科创50收涨0.36%。")),
        PooledQuote("QUO-2", "市场情绪偏谨慎。", False, "factual", None,
                    span_start=len("科创50收涨0.36%。"), span_end=len(_RAW_A)),
    ], raw_content=_RAW_A),
]


async def test_assemble_validates_stubbed_output(fixtures_dir_writer):
    payload = json.loads((fixtures_dir_writer / "deepseek_writer.json").read_text("utf-8"))
    content = payload["choices"][0]["message"]["content"]

    async def stub_call(messages):
        assert any("QUOTE POOL" in m["content"] for m in messages)
        return content

    out = await assemble(POOL, call=stub_call, session_date=date(2026, 7, 23))
    # local_id passes through unchanged
    assert out.claims[0].local_id == "c-001"
    # alias q1 must be mapped back to real uuid QUO-1
    assert out.claims[0].quote_ids == ["QUO-1"]
    # alias s1 in sentence[1] must be mapped back to real uuid SRC-A
    assert out.sentences[1].source_ids == ["SRC-A"]


async def test_assemble_rejects_unresolvable_ids():
    async def bad_call(messages):
        # q99 is not a valid alias for the pool (only q1, q2 exist)
        return json.dumps({
            "claims": [{"id": "c-1", "statement": "x", "quote_ids": ["q99"]}],
            "sentences": [{"sentence": "句子。", "claim_ids": ["c-1"],
                           "source_ids": ["s1"], "sentence_type": "factual"}],
        })

    import pytest

    from marketwind.writer.schema import SchemaViolation
    with pytest.raises(SchemaViolation):
        await assemble(POOL, call=bad_call, session_date=date(2026, 7, 23))
