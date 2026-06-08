# tests/scheduling/test_gather.py
from datetime import date, datetime, timezone

from marketwind.scout.domain import Quote
from marketwind.scout.gather import build_pool
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
