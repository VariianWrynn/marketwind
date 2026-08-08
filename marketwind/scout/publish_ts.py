"""G2.5: Per-site publish_ts parsing from HTML.

Parsers extract publish timestamps from saved HTML using regex on meta tags
and structured data. No network access — all tests use fixture HTML.

Unknown site or unparseable → None, never a guess (fail closed).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable

_CST = timezone(offset=__import__("datetime").timedelta(hours=8))

# Common meta tag patterns for publish timestamps
_META_PATTERNS = [
    re.compile(r'<meta\s+(?:property|name)="(?:article:published_time|og:article:published_time|publishdate|pub_date|publish_time)"\s+content="([^"]+)"', re.I),
    re.compile(r'<meta\s+content="([^"]+)"\s+(?:property|name)="(?:article:published_time|publishdate|pub_date)"', re.I),
]

# JSON-LD datePublished
_JSONLD_PATTERN = re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I)

# Inline date patterns in article body
_INLINE_PATTERNS = {
    "sina": re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})'),
    "cls": re.compile(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})'),
    "eastmoney": re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2}):(\d{2})'),
    "ifeng": re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})'),
}


def _parse_iso(s: str) -> datetime | None:
    """Parse ISO 8601 timestamp to datetime (CST assumed if no tz)."""
    s = s.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_CST)
            return dt
        except ValueError:
            continue
    return None


def _try_meta(html: str) -> datetime | None:
    for pat in _META_PATTERNS:
        m = pat.search(html)
        if m:
            dt = _parse_iso(m.group(1))
            if dt is not None:
                return dt
    return None


def _try_jsonld(html: str) -> datetime | None:
    m = _JSONLD_PATTERN.search(html)
    if m:
        return _parse_iso(m.group(1))
    return None


def _try_inline(html: str, domain: str) -> datetime | None:
    for key, pat in _INLINE_PATTERNS.items():
        if key in domain:
            m = pat.search(html)
            if m:
                groups = m.groups()
                try:
                    if len(groups) == 5:
                        y, mo, d, h, mi = (int(g) for g in groups)
                        return datetime(y, mo, d, h, mi, tzinfo=_CST)
                    elif len(groups) == 6:
                        y, mo, d, h, mi, s = (int(g) for g in groups)
                        return datetime(y, mo, d, h, mi, s, tzinfo=_CST)
                except (ValueError, OverflowError):
                    pass
    return None


# Registry: domain → parser function. Each parser takes (html, domain) and
# returns datetime | None. Unknown domains fall through to None.
_PARSERS: dict[str, Callable[[str, str], datetime | None]] = {}


def _register(*domains: str):
    """Decorator: register a parser for one or more domains."""
    def decorator(fn):
        for d in domains:
            _PARSERS[d] = fn
        return fn
    return decorator


@_register("finance.sina.com.cn", "sina.com.cn")
def _parse_sina(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_inline(html, domain)


@_register("cls.cn")
def _parse_cls(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_jsonld(html) or _try_inline(html, domain)


@_register("stcn.com")
def _parse_stcn(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_jsonld(html)


@_register("finance.eastmoney.com", "eastmoney.com")
def _parse_eastmoney(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_inline(html, domain)


@_register("i.ifeng.com", "ifeng.com")
def _parse_ifeng(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_inline(html, domain)


@_register("stock.cngold.org", "cngold.org")
def _parse_cngold(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_jsonld(html)


@_register("nbd.com.cn")
def _parse_nbd(html: str, domain: str) -> datetime | None:
    return _try_meta(html) or _try_jsonld(html)


def parse_publish_ts(html: str, domain: str) -> datetime | None:
    """Extract publish timestamp from HTML for a known domain.

    Returns None for unknown domains or unparseable HTML — never a guess.
    """
    parser = _PARSERS.get(domain)
    if parser is None:
        return None
    try:
        return parser(html, domain)
    except Exception:
        return None
