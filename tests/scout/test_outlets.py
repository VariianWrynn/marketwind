import pytest

from marketwind.scout.outlets import domain_of, is_quote_aggregator

CASES = [
    ("https://www.cls.cn/detail/123", "cls.cn"),
    ("http://finance.sina.com.cn/stock/x.shtml", "finance.sina.com.cn"),
    ("https://m.cls.cn/a/456?from=wx", "m.cls.cn"),
    ("https://WWW.STCN.COM/article/789.html", "stcn.com"),
]


@pytest.mark.parametrize("url,expected", CASES)
def test_domain_of(url, expected):
    assert domain_of(url) == expected


def test_strips_leading_www_only():
    assert domain_of("https://www.eastmoney.com/x") == "eastmoney.com"
    assert domain_of("https://wwwx.eastmoney.com/x") == "wwwx.eastmoney.com"


def test_quote_aggregator_hosts_are_flagged():
    # evidence (raw-fetch probe): these are price/quote-table pages that return
    # 0 disclosure text and never trace to a constituent primary — skip the fetch.
    assert is_quote_aggregator("q.stock.sohu.com") is True
    assert is_quote_aggregator("quote.eastmoney.com") is True


def test_article_hosts_are_not_flagged():
    # article subdomains carry real disclosure text — must NOT be skipped
    assert is_quote_aggregator("caifuhao.eastmoney.com") is False
    assert is_quote_aggregator("finance.sina.com.cn") is False
    assert is_quote_aggregator("cls.cn") is False
