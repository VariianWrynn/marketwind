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
