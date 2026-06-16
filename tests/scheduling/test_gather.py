# tests/scheduling/test_gather.py
from datetime import date, datetime, timezone

from marketwind.scout.domain import Quote
from marketwind.scout.gather import _PER_QUERY_CAP, build_pool
from marketwind.scout.query import build_recap_queries

_NOW = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_PREV = date(2026, 6, 5)
_QUERIES = build_recap_queries(_PREV)


def _q(text: str) -> Quote:
    return Quote(text=text, span_start=0, span_end=len(text),
                 context_before=None, context_after=None, is_quantitative=False)


def _search_returning(mapping):
    async def _search(query: str):
        return mapping.get(query, [])
    return _search


async def _fetch_ok(url: str) -> str:
    return f"<html>{url}</html>"


def _parse_one_quote(html: str):
    return ("raw:" + html, [_q("一句话。")])


def _persist_recorder(store):
    async def _persist(src):
        store.append(src)
    return _persist


async def test_dedup_same_url_across_queries():
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")],
            _QUERIES[1]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert len(out) == 1
    assert out[0].url == "https://a.cn/x"
    assert len(store) == 1


async def test_fetch_error_is_skipped():
    async def _fetch_boom(url: str) -> str:
        raise RuntimeError("nav failed")
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_boom, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert out == []
    assert store == []


async def test_empty_quotes_is_skipped():
    def _parse_empty(html: str):
        return ("", [])
    hits = {_QUERIES[0]: [("https://a.cn/x", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_empty,
                           persist=_persist_recorder(store), now=_NOW)
    assert out == []


async def test_kept_source_carries_domain_quotes_and_ingest_ts():
    hits = {_QUERIES[0]: [("https://news.example.cn/p", "s")]}
    store = []
    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_fetch_ok, parse=_parse_one_quote,
                           persist=_persist_recorder(store), now=_NOW)
    assert out[0].domain == "news.example.cn"
    assert out[0].publish_ts == _NOW
    assert out[0].raw_content.startswith("raw:")
    assert out[0].quotes[0].attached_primary_url is None


async def test_build_pool_issues_per_name_queries():
    issued: list[str] = []

    async def _recording_search(query: str):
        issued.append(query)
        return []

    await build_pool(prev_session=_PREV, names=["中芯国际"],
                     search=_recording_search, fetch_page=_fetch_ok,
                     parse=_parse_one_quote, persist=_persist_recorder([]),
                     now=_NOW)
    joined = "\n".join(issued)
    assert "中芯国际" in joined            # per-name query was issued
    assert any("收盘 复盘" in q for q in issued)   # macro recap still issued


async def test_build_pool_caps_results_per_query():
    # one query returns more hits than the cap; only the top-_PER_QUERY_CAP are
    # fetched — bounds the Playwright fan-out (A).
    n = _PER_QUERY_CAP + 2
    urls = [f"https://news{i}.example.cn/a" for i in range(n)]
    hits = {_QUERIES[0]: [(u, "s") for u in urls]}
    fetched: list[str] = []

    async def _recording_fetch(url: str) -> str:
        fetched.append(url)
        return f"<html>{url}</html>"

    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_recording_fetch, parse=_parse_one_quote,
                           persist=_persist_recorder([]), now=_NOW)
    assert len(fetched) == _PER_QUERY_CAP       # only top-N fetched, not all n
    assert fetched == urls[:_PER_QUERY_CAP]     # the top-ranked ones, in order
    assert len(out) == _PER_QUERY_CAP


async def test_build_pool_skips_quote_aggregator_hosts():
    # a price/quote-table host is never fetched (C); the article host is kept.
    good = "https://caifuhao.eastmoney.com/news/123"
    junk = "https://q.stock.sohu.com/zs/000688/index.shtml"
    hits = {_QUERIES[0]: [(good, "s"), (junk, "s")]}
    fetched: list[str] = []

    async def _recording_fetch(url: str) -> str:
        fetched.append(url)
        return f"<html>{url}</html>"

    out = await build_pool(prev_session=_PREV, search=_search_returning(hits),
                           fetch_page=_recording_fetch, parse=_parse_one_quote,
                           persist=_persist_recorder([]), now=_NOW)
    assert junk not in fetched                  # expensive fetch skipped
    assert [s.url for s in out] == [good]
