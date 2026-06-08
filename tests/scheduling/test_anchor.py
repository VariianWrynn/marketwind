# tests/scheduling/test_anchor.py
from datetime import date, datetime, timezone

from marketwind.scheduling.anchor import anchor_utc


def test_premarket_anchor_is_dst_aware_summer():
    # 18:00 ET (= 16:00 US close + 2h) on a summer date is EDT (UTC-4) -> 22:00 UTC.
    got = anchor_utc(date(2026, 6, 8), 18, 0, "America/New_York")
    assert got == datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)


def test_premarket_anchor_is_dst_aware_winter():
    # 18:00 ET on a winter date is EST (UTC-5) -> 23:00 UTC.
    got = anchor_utc(date(2026, 1, 6), 18, 0, "America/New_York")
    assert got == datetime(2026, 1, 6, 23, 0, tzinfo=timezone.utc)


def test_main_report_anchor_cst():
    # 07:00 CST (UTC+8) -> 23:00 UTC the previous calendar day.
    got = anchor_utc(date(2026, 6, 8), 7, 0, "Asia/Shanghai")
    assert got == datetime(2026, 6, 7, 23, 0, tzinfo=timezone.utc)
