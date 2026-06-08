"""A-share trading-calendar helpers.

The pure picker takes the session list injected (offline-testable). The live
loader fetches + caches akshare's calendar (D-22); it is exercised in the smoke
run, not unit tests.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache


def prev_trading_session(today: date, sessions: list[date]) -> date:
    """Latest trading session strictly before `today`. Never naive yesterday."""
    prior = [d for d in sessions if d < today]
    if not prior:
        raise ValueError(f"no trading session before {today}")
    return max(prior)


@lru_cache(maxsize=1)
def _load_sessions() -> tuple[date, ...]:  # pragma: no cover - live akshare call
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    return tuple(d if isinstance(d, date) else d.date() for d in df["trade_date"])


def live_prev_trading_session(today: date) -> date:  # pragma: no cover - live
    return prev_trading_session(today, list(_load_sessions()))


def is_trading_session(today: date, sessions: list[date]) -> bool:
    """True iff `today` is one of the known trading sessions."""
    return today in set(sessions)
