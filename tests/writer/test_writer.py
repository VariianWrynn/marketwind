import json

from marketwind.writer.domain import PooledQuote, PooledSource
from marketwind.writer.writer import assemble

POOL = [
    PooledSource("s1", "https://m.cls.cn/a/1", "m.cls.cn", False, [
        PooledQuote("q1", "科创50收涨0.36%。", True, "data", "https://cninfo.com.cn/x"),
        PooledQuote("q2", "市场情绪偏谨慎。", False, "factual", None),
    ]),
]


async def test_assemble_validates_stubbed_output(fixtures_dir_writer):
    payload = json.loads((fixtures_dir_writer / "deepseek_writer.json").read_text("utf-8"))
    content = payload["choices"][0]["message"]["content"]

    async def stub_call(messages):
        assert any("QUOTE POOL" in m["content"] for m in messages)
        return content

    out = await assemble(POOL, call=stub_call)
    assert out.claims[0].local_id == "c-001"
    assert out.sentences[1].source_ids == ["s1"]


async def test_assemble_rejects_unresolvable_ids():
    async def bad_call(messages):
        return json.dumps({
            "claims": [{"id": "c-1", "statement": "x", "quote_ids": ["q-nope"]}],
            "sentences": [{"sentence": "句子。", "claim_ids": ["c-1"],
                           "source_ids": ["s1"], "sentence_type": "factual"}],
        })

    import pytest

    from marketwind.writer.schema import SchemaViolation
    with pytest.raises(SchemaViolation):
        await assemble(POOL, call=bad_call)
