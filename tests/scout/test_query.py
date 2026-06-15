from datetime import date

from marketwind.scout.discover import parse_bocha_response
from marketwind.scout.query import build_constituent_queries, build_recap_queries


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


def test_queries_include_company_event_dimensions():
    qs = build_recap_queries(date(2026, 5, 29))
    joined = " ".join(qs)
    # corpus must now reach company-level primary events, not just index recap
    assert "业绩" in joined
    assert "募资" in joined or "定增" in joined
    assert "IPO" in joined or "首发" in joined
    # new event queries stay date-anchored / scope-anchored
    assert "成份股" in joined or "科创板" in joined


def test_constituent_queries_one_anchored_earnings_query_per_name():
    qs = build_constituent_queries(["中芯国际", "海光信息"], date(2026, 6, 12))
    assert qs == [
        "中芯国际 6月12日 业绩 净利润",
        "海光信息 6月12日 业绩 净利润",
    ]


def test_constituent_queries_empty_names_is_empty():
    assert build_constituent_queries([], date(2026, 6, 12)) == []


def test_parse_bocha_response(fixtures_dir):
    import json
    raw = json.loads((fixtures_dir / "bocha_search.json").read_text(encoding="utf-8"))
    hits = parse_bocha_response(raw)
    assert hits == [
        ("https://m.cls.cn/a/1", "科创50收盘涨0.36%"),
        ("https://finance.sina.com.cn/x", "成交额3.24万亿"),
    ]
