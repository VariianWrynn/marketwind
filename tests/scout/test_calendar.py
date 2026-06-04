from datetime import date

import pytest

from marketwind.scout.calendar import prev_trading_session


# A Friday, then a weekend gap, then Monday.
SESSIONS = [date(2026, 5, 28), date(2026, 5, 29), date(2026, 6, 1), date(2026, 6, 2)]


def test_prev_session_skips_weekend():
    # Monday 2026-06-01 → prior session is Friday 2026-05-29
    assert prev_trading_session(date(2026, 6, 1), SESSIONS) == date(2026, 5, 29)


def test_prev_session_strictly_before_today():
    # On a trading day, prev is the session before it, not itself.
    assert prev_trading_session(date(2026, 6, 2), SESSIONS) == date(2026, 6, 1)


def test_prev_session_on_non_trading_day():
    # Sunday 2026-05-31 → latest session before it is Friday 2026-05-29
    assert prev_trading_session(date(2026, 5, 31), SESSIONS) == date(2026, 5, 29)


def test_raises_when_no_prior_session():
    with pytest.raises(ValueError):
        prev_trading_session(date(2026, 5, 28), SESSIONS)
