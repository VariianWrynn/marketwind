# tests/scheduling/test_calendar_gate.py
from datetime import date

from marketwind.scout.calendar import is_trading_session

_SESSIONS = [date(2026, 6, 5), date(2026, 6, 8), date(2026, 6, 9)]  # Fri, Mon, Tue


def test_trading_day_is_in_session_list():
    assert is_trading_session(date(2026, 6, 8), _SESSIONS) is True


def test_weekend_is_not_a_session():
    assert is_trading_session(date(2026, 6, 6), _SESSIONS) is False  # Saturday
