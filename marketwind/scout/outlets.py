"""Derive a normalized domain from a URL. P1: distinct-domain identity only.

Outlet-group normalization (collapsing 新浪系 / 财联社系 to one identity) is a
P2 concern and is intentionally NOT done here (spec §2 Out-of-scope).
"""

from __future__ import annotations

from urllib.parse import urlparse


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[len("www."):]
    return host


# Price/quote-table hosts that yield no disclosure text and never trace to a
# constituent primary (evidence: the raw-fetch probe). Skipping them before the
# fetch saves the expensive Playwright page-load at zero recall cost. Exact-match
# on the normalized domain; extend as new junk hosts surface.
_QUOTE_AGGREGATOR_HOSTS = frozenset({
    "quote.eastmoney.com",
    "q.stock.sohu.com",
})


def is_quote_aggregator(domain: str) -> bool:
    return domain in _QUOTE_AGGREGATOR_HOSTS
