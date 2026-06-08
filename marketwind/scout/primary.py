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

_CNINFO_CATEGORY = {
    "ipo": "首发",
    "fundraising": "增发",
    "earnings": "业绩预告",
}


def primary_venue_for(claim_type: str) -> str | None:
    return _VENUE.get(claim_type)


def cninfo_category_for(claim_type: str) -> str:
    """Map a claim type to a cninfo disclosure category, '' for unknown."""
    return _CNINFO_CATEGORY.get(claim_type, "")


def select_disclosure_url(records: list[dict]) -> str | None:
    """Return the first non-empty '公告链接' value, or None."""
    for record in records:
        url = record.get("公告链接", "")
        if url:
            return str(url)
    return None


def disclosure_window(on_date: datetime.date) -> tuple[str, str]:
    """Return (start, end) as 'YYYYMMDD' strings: end=on_date, start=on_date-90d."""
    start = on_date - datetime.timedelta(days=90)
    return (start.strftime("%Y%m%d"), on_date.strftime("%Y%m%d"))


async def trace_to_primary(claim_type: str, company: str, on_date) -> str | None:  # pragma: no cover - live
    """Return the primary disclosure URL for a claim, or None if not found."""
    venue = primary_venue_for(claim_type)
    if venue != "cninfo":
        return None  # P1 traces cninfo announcements; other venues are P2
    import akshare as ak

    start, end = disclosure_window(on_date)
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=company, market="沪深京",
        category=cninfo_category_for(claim_type),
        start_date=start, end_date=end,
    )
    if df is None or df.empty:
        return None
    return select_disclosure_url(df.to_dict("records"))
