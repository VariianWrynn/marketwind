from marketwind.scout.cninfo_pdf import derive_pdf_url

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


from marketwind.scout.cninfo_pdf import extract_pdf_text


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
