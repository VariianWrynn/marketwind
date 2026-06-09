"""Fetch + text-extract a cninfo disclosure PDF so the number-match guard can
verify a quoted figure. Derive the static PDF URL from the akshare detail URL's
query params (no extra API call); extract text with pypdf; every limb fails
closed ("" / None → no attach), so the chain never launders (Iron Law 3)."""
from __future__ import annotations

import io
from urllib.parse import parse_qs, urlparse

from pypdf import PdfReader


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


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Concatenate the text layer of every page. Returns "" on any pypdf error
    or when there is no extractable text (image-only / mojibake PDFs) — the
    caller then finds no number and declines to attach (fails closed)."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


async def fetch_cninfo_disclosure(client, detail_url: str) -> str:
    """Derive the PDF URL, download it, and return its extracted text.

    `client` is an httpx.AsyncClient-like object (awaitable .get returning a
    response with .status_code, .headers, .content). Any failure — underivable
    URL, non-200, non-PDF content-type, or extraction error — returns "" so the
    caller declines to attach (fails closed; never launders, Iron Law 3)."""
    pdf_url = derive_pdf_url(detail_url)
    if pdf_url is None:
        return ""
    resp = await client.get(pdf_url)
    if resp.status_code != 200:
        return ""
    if "application/pdf" not in resp.headers.get("content-type", ""):
        return ""
    return extract_pdf_text(resp.content)
