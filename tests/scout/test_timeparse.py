from datetime import datetime, timedelta, timezone

import pytest

from marketwind.scout.timeparse import CN_TZ, parse_publish_ts

INGEST = datetime(2026, 6, 1, 9, 0, tzinfo=CN_TZ)


def test_full_date_with_year():
    ts = parse_publish_ts("2026年5月28日 09:30", INGEST)
    assert ts == datetime(2026, 5, 28, 9, 30, tzinfo=CN_TZ)


def test_full_date_no_time_defaults_midnight():
    ts = parse_publish_ts("2026年5月28日", INGEST)
    assert ts == datetime(2026, 5, 28, 0, 0, tzinfo=CN_TZ)


def test_bare_month_day_takes_most_recent_occurrence():
    ts = parse_publish_ts("5月28日 09:30", INGEST)
    assert ts == datetime(2026, 5, 28, 9, 30, tzinfo=CN_TZ)


def test_bare_month_day_rolls_back_a_year_when_future():
    ingest = datetime(2026, 1, 2, 9, 0, tzinfo=CN_TZ)
    ts = parse_publish_ts("12月30日", ingest)
    assert ts == datetime(2025, 12, 30, 0, 0, tzinfo=CN_TZ)


def test_relative_hours_ago():
    ts = parse_publish_ts("3小时前", INGEST)
    assert ts == INGEST - timedelta(hours=3)


def test_jinchen_is_same_day_early_morning():
    ts = parse_publish_ts("今晨", INGEST)
    assert ts.date() == INGEST.date()
    assert ts.hour <= 8


def test_unparseable_raises():
    with pytest.raises(ValueError):
        parse_publish_ts("不是时间", INGEST)
