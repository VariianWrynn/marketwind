from datetime import date, datetime, timezone

from marketwind.scout.cninfo_pdf import derive_pdf_url, extract_pdf_text, fetch_cninfo_disclosure
from marketwind.scout.domain import Quote, Source
from marketwind.scout.enrich import enrich_primary

_DETAIL = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&announcementId=1219447112&orgId=gshk0000981"
           "&announcementTime=2024-03-29")


def test_derive_pdf_url_builds_static_finalpage_url():
    assert derive_pdf_url(_DETAIL) == (
        "http://static.cninfo.com.cn/finalpage/2024-03-29/1219447112.PDF"
    )


def test_derive_pdf_url_missing_announcement_id_returns_none():
    url = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&orgId=gshk0000981&announcementTime=2024-03-29")
    assert derive_pdf_url(url) is None


def test_derive_pdf_url_missing_time_returns_none():
    url = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&announcementId=1219447112&orgId=gshk0000981")
    assert derive_pdf_url(url) is None


def test_derive_pdf_url_non_cninfo_url_returns_none():
    assert derive_pdf_url("https://news.example.com/article/123") is None


def test_derive_pdf_url_whitespace_announcement_id_returns_none():
    url = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688981"
           "&announcementId=%20&orgId=gshk0000981&announcementTime=2024-03-29")
    assert derive_pdf_url(url) is None


def test_derive_pdf_url_empty_string_returns_none():
    assert derive_pdf_url("") is None


def _build_minimal_pdf(text: str) -> bytes:
    """A correct one-page Helvetica PDF containing `text` (ASCII/latin-1)."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = b"BT /F1 18 Tf 20 100 Td (" + text.encode("latin-1") + b") Tj ET\n"
    objs.append(b"<</Length " + str(len(stream)).encode() + b">>stream\n"
                + stream + b"endstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj" + body + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += b"trailer<</Root 1 0 R/Size " + str(len(objs) + 1).encode() + b">>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return out


def test_extract_pdf_text_reads_text_layer():
    pdf = _build_minimal_pdf("MarketWind 123.45")
    assert "MarketWind 123.45" in extract_pdf_text(pdf)


def test_extract_pdf_text_corrupt_bytes_returns_empty():
    assert extract_pdf_text(b"not a pdf at all") == ""


_DETAIL_OK = ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=688256"
              "&announcementId=1219210058&orgId=nssc1000595"
              "&announcementTime=2024-02-29")


class _FakeResp:
    def __init__(self, status_code, content, content_type="application/pdf"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


class _FakeClient:
    """Records GET calls and returns a queued response."""
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        return self._resp


async def test_fetch_disclosure_happy_path_returns_extracted_text():
    pdf = _build_minimal_pdf("net profit 12.34%")
    client = _FakeClient(_FakeResp(200, pdf))
    text = await fetch_cninfo_disclosure(client, _DETAIL_OK)
    assert "net profit 12.34%" in text
    assert client.calls == [
        "http://static.cninfo.com.cn/finalpage/2024-02-29/1219210058.PDF"
    ]


async def test_fetch_disclosure_non_200_returns_empty():
    client = _FakeClient(_FakeResp(404, b""))
    assert await fetch_cninfo_disclosure(client, _DETAIL_OK) == ""


async def test_fetch_disclosure_wrong_content_type_returns_empty():
    client = _FakeClient(_FakeResp(200, b"<html>shell</html>", "text/html"))
    assert await fetch_cninfo_disclosure(client, _DETAIL_OK) == ""


async def test_fetch_disclosure_underivable_url_skips_get():
    client = _FakeClient(_FakeResp(200, _build_minimal_pdf("x")))
    assert await fetch_cninfo_disclosure(client, "https://news.example.com/x") == ""
    assert client.calls == []  # no GET issued when URL is not derivable


_CONS = {"中芯国际": "688981"}
_PUB = datetime(2024, 2, 29, tzinfo=timezone.utc)  # publish_ts is non-optional, tz-aware


def _quote(text):
    return Quote(text=text, span_start=0, span_end=len(text), context_before=None,
                 context_after=None, is_quantitative=True)


def _source(quotes):
    return Source(url="https://news.example.com/a", domain="example.com",
                  publish_ts=_PUB, raw_content="x", quotes=quotes)


async def _classify_none(text):
    return None


async def test_integration_pdf_number_match_attaches_primary():
    pdf = _build_minimal_pdf("SMIC net profit margin 12.34%")
    client = _FakeClient(_FakeResp(200, pdf))

    async def trace(claim_type, symbol, on_date):
        assert (claim_type, symbol) == ("earnings", "688981")
        return _DETAIL_OK  # a cninfo detail URL → derivable PDF

    async def fetch(url):
        return await fetch_cninfo_disclosure(client, url)

    out = await enrich_primary(
        [_source([_quote("中芯国际净利润率同比12.34%")])],
        classify=_classify_none, trace=trace, fetch=fetch,
        constituents=_CONS, on_date=date(2024, 2, 29),
    )
    assert out[0].quotes[0].attached_primary_url == _DETAIL_OK


async def test_integration_pdf_wrong_number_does_not_attach():
    pdf = _build_minimal_pdf("SMIC net profit margin 99.99%")
    client = _FakeClient(_FakeResp(200, pdf))

    async def trace(claim_type, symbol, on_date):
        return _DETAIL_OK

    async def fetch(url):
        return await fetch_cninfo_disclosure(client, url)

    out = await enrich_primary(
        [_source([_quote("中芯国际净利润率同比12.34%")])],
        classify=_classify_none, trace=trace, fetch=fetch,
        constituents=_CONS, on_date=date(2024, 2, 29),
    )
    assert out[0].quotes[0].attached_primary_url is None
