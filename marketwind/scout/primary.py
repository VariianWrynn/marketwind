"""Trace one media-reported number to its primary disclosure (Gap-1).

P1 proves the mechanism: route a claim-type to the right primary venue, then
(live) look it up and return the disclosure URL. Full mapping table is P2.
"""

from __future__ import annotations

import datetime

_VENUE = {
    "ipo": "cninfo",
    "fundraising": "cninfo",
    "earnings": "cninfo",
    "shareholding_reduction": "exchange",
    "policy": "regulator",
}

def primary_venue_for(claim_type: str) -> str | None:
    return _VENUE.get(claim_type)


def select_disclosure_urls(records: list[dict]) -> list[str]:
    """Return every non-empty '公告链接' value as str, order preserved."""
    urls = []
    for record in records:
        url = record.get("公告链接", "")
        if url:
            urls.append(str(url))
    return urls


def disclosure_window(on_date: datetime.date) -> tuple[str, str]:
    """Return (start, end) as 'YYYYMMDD' strings: end=on_date, start=on_date-90d."""
    start = on_date - datetime.timedelta(days=90)
    return (start.strftime("%Y%m%d"), on_date.strftime("%Y%m%d"))


async def trace_to_primary(claim_type: str, company: str, on_date) -> list[str]:  # pragma: no cover - live
    """Return candidate primary disclosure URLs for a claim (empty if none)."""
    venue = primary_venue_for(claim_type)
    if venue != "cninfo":
        return []  # P1 traces cninfo announcements; other venues are P2
    import akshare as ak

    start, end = disclosure_window(on_date)
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=company, market="沪深京",
        category="",
        start_date=start, end_date=end,
    )
    if df is None or df.empty:
        return []
    return select_disclosure_urls(df.to_dict("records"))[:8]
