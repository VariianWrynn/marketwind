import pytest

from marketwind.scout.outlets import domain_of

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
