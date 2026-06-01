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
