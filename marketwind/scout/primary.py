"""Trace one media-reported number to its primary disclosure (Gap-1).

P1 proves the mechanism: route a claim-type to the right primary venue, then
(live) look it up and return the disclosure URL. Full mapping table is P2.
"""

from __future__ import annotations

_VENUE = {
    "ipo": "cninfo",
    "fundraising": "cninfo",
    "earnings": "cninfo",
    "shareholding_reduction": "exchange",
    "policy": "regulator",
}


def primary_venue_for(claim_type: str) -> str | None:
    return _VENUE.get(claim_type)


async def trace_to_primary(claim_type: str, company: str, on_date) -> str | None:  # pragma: no cover - live
    """Return the primary disclosure URL for a claim, or None if not found."""
    venue = primary_venue_for(claim_type)
    if venue != "cninfo":
        return None  # P1 traces cninfo announcements; other venues are P2
    import akshare as ak

    df = ak.stock_notice_report(symbol=company)  # company announcements
    if df is None or df.empty:
        return None
    return str(df.iloc[0].get("url")) or None
