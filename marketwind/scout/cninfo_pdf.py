"""Fetch + text-extract a cninfo disclosure PDF so the number-match guard can
verify a quoted figure. Derive the static PDF URL from the akshare detail URL's
query params (no extra API call); extract text with pypdf; every limb fails
closed ("" / None → no attach), so the chain never launders (Iron Law 3)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def derive_pdf_url(detail_url: str) -> str | None:
    """Build the static cninfo PDF URL from a disclosure detail URL.

    Returns None if the URL is empty or lacks a usable
    announcementId/announcementTime (non-cninfo or malformed) — caller
    degrades to no-attach.
    """
    if not detail_url:
        return None
    qs = parse_qs(urlparse(detail_url).query)
    ann_id = (qs.get("announcementId", [""])[0] or "").strip()
    ann_time = (qs.get("announcementTime", [""])[0] or "").strip()
    if not ann_id or not ann_time:
        return None
    # cninfo static host is HTTP-only (no TLS on this path) — do not "fix" to https.
    return f"http://static.cninfo.com.cn/finalpage/{ann_time}/{ann_id}.PDF"
