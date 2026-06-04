from marketwind.writer.domain import (
    DraftClaim, DraftSentence, PooledQuote, PooledSource, WriterOutput,
)


def test_value_objects_construct():
    q = PooledQuote("q1", "科创50收涨0.36%。", True, "data", "https://cninfo.com.cn/x")
    s = PooledSource("s1", "https://m.cls.cn/a/1", "m.cls.cn", False, [q])
    out = WriterOutput(
        claims=[DraftClaim("c-001", "科创50上一交易日收涨0.36%", ["q1"])],
        sentences=[DraftSentence("科创50上一交易日收涨0.36%。", ["c-001"], ["s1"], "factual")],
    )
    assert s.quotes[0].quote_id == "q1"
    assert out.sentences[0].claim_ids == ["c-001"]
