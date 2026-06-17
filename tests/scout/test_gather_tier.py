import datetime as dt

from marketwind.scout.domain import Quote
from marketwind.scout.gather import build_pool


async def test_official_domain_source_marked_primary():
    captured = []
    async def search(q): return [("https://www.cninfo.com.cn/x", "snip")]
    async def fetch_page(u): return "<html/>"
    def parse(html): return ("正文", [Quote("正文", 0, 2, None, None, True)])
    async def persist(src): captured.append(src)
    await build_pool(prev_session=dt.date(2026, 6, 16), names=[], search=search,
                     fetch_page=fetch_page, parse=parse, persist=persist,
                     now=dt.datetime(2026, 6, 17))
    assert captured and captured[0].is_primary is True


async def test_trusted_domain_source_not_marked_primary():
    captured = []
    async def search(q): return [("https://finance.sina.com.cn/x", "snip")]
    async def fetch_page(u): return "<html/>"
    def parse(html): return ("正文", [Quote("正文", 0, 2, None, None, True)])
    async def persist(src): captured.append(src)
    await build_pool(prev_session=dt.date(2026, 6, 16), names=[], search=search,
                     fetch_page=fetch_page, parse=parse, persist=persist,
                     now=dt.datetime(2026, 6, 17))
    assert captured and captured[0].is_primary is False
