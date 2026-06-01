from datetime import date

from marketwind.scout.discover import parse_bocha_response
from marketwind.scout.query import build_recap_queries


def test_queries_have_date_anchors():
    qs = build_recap_queries(date(2026, 5, 29))
    assert qs, "expected queries"
    # every query must anchor to the prior session — never undated
    for q in qs:
        assert ("5月29日" in q) or ("上一交易日" in q) or ("收盘" in q)


def test_queries_cover_recap_dimension():
    qs = build_recap_queries(date(2026, 5, 29))
    joined = " ".join(qs)
    assert "科创50" in joined
    assert "复盘" in joined or "收盘" in joined


def test_parse_bocha_response(fixtures_dir):
    import json
    raw = json.loads((fixtures_dir / "bocha_search.json").read_text(encoding="utf-8"))
    hits = parse_bocha_response(raw)
    assert hits == [
        ("https://m.cls.cn/a/1", "科创50收盘涨0.36%"),
        ("https://finance.sina.com.cn/x", "成交额3.24万亿"),
    ]
