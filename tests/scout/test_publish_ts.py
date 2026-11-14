"""Tests for G2.5 publish_ts parsing — all use inline HTML fixtures, no network."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from marketwind.scout.publish_ts import parse_publish_ts

_CST = timezone(offset=timedelta(hours=8))


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

SINA_HTML = """
<html><head>
<meta property="article:published_time" content="2026-05-27T09:30:00+08:00">
</head><body>2026年5月27日 09:30 新浪财经讯</body></html>
"""

CLS_HTML = """
<html><head>
<meta name="publishdate" content="2026-05-27T14:22:00+08:00">
</head><body><script type="application/ld+json">{"datePublished":"2026-05-27T14:22:00+08:00"}</script></body></html>
"""

STCN_HTML = """
<html><head>
<meta property="article:published_time" content="2026-05-27T10:15:00+08:00">
</head><body></body></html>
"""

EASTMONEY_HTML = """
<html><head></head>
<body><span class="news-time">2026年5月27日 11:45:30</span></body></html>
"""

IFENG_HTML = """
<html><head>
<meta property="article:published_time" content="2026-05-27T08:00:00+08:00">
</head><body>2026年5月27日 08:00 凤凰网</body></html>
"""

GARBLED_HTML = """
<html><head></head><body>锘挎枃浠跺凡涓㈠け</body></html>
"""

EMPTY_HTML = ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sina_meta_tag():
    dt = parse_publish_ts(SINA_HTML, "finance.sina.com.cn")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 27
    assert dt.hour == 9
    assert dt.minute == 30


def test_cls_meta_tag():
    dt = parse_publish_ts(CLS_HTML, "cls.cn")
    assert dt is not None
    assert dt.hour == 14
    assert dt.minute == 22


def test_stcn_meta_tag():
    dt = parse_publish_ts(STCN_HTML, "stcn.com")
    assert dt is not None
    assert dt.hour == 10
    assert dt.minute == 15


def test_eastmoney_inline():
    dt = parse_publish_ts(EASTMONEY_HTML, "finance.eastmoney.com")
    assert dt is not None
    assert dt.hour == 11
    assert dt.minute == 45
    assert dt.second == 30


def test_ifeng_meta_tag():
    dt = parse_publish_ts(IFENG_HTML, "i.ifeng.com")
    assert dt is not None
    assert dt.hour == 8


def test_unknown_domain_returns_none():
    assert parse_publish_ts(SINA_HTML, "totally-unknown.com") is None


def test_garbled_html_returns_none():
    assert parse_publish_ts(GARBLED_HTML, "finance.sina.com.cn") is None


def test_empty_html_returns_none():
    assert parse_publish_ts(EMPTY_HTML, "cls.cn") is None


def test_parser_exception_returns_none():
    """Parser errors must not propagate — fail closed with None."""
    assert parse_publish_ts(None, "cls.cn") is None  # type: ignore[arg-type]


def test_all_return_cst_timezone():
    dt = parse_publish_ts(SINA_HTML, "finance.sina.com.cn")
    assert dt is not None
    assert dt.tzinfo is not None
