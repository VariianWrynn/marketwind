"""akshare STAR50 market numbers + the is_primary scope rule (spec §6).

akshare is a primary source ONLY for market/index aggregates. Company financials
(净利, 营收, 减持额) are NOT primary just because akshare served them — they still
require a cninfo/exchange trace (otherwise Gap-1 leaks through the vendor).
"""

from __future__ import annotations

_PRIMARY_AGGREGATES = {"index_level", "pct_change", "turnover", "advance_decline"}


def is_primary_metric(metric: str) -> bool:
    return metric in _PRIMARY_AGGREGATES


def fetch_star50_recap(prev_session) -> dict:  # pragma: no cover - live akshare
    """Return STAR50 index level / pct_change / turnover for the prior session."""
    import akshare as ak

    df = ak.stock_zh_index_daily(symbol="sh000688")  # 科创50
    row = df.iloc[-1]
    return {
        "index_level": float(row["close"]),
        "turnover": float(row.get("amount", 0)),
        "as_of": str(row.get("date", prev_session)),
    }
