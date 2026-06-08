# tests/scheduling/test_freshness.py
from datetime import datetime, time, timedelta, timezone

from marketwind.scheduling.anchor import freshness_ok

# Anchor: 22:00 UTC = 06:00 CST next morning (a pre-market fire).
_ANCHOR = datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)
_CEIL = time(10, 0)


def test_on_time_run_is_fresh():
    now = _ANCHOR + timedelta(minutes=10)  # 06:10 CST
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=90, ceiling_cst=_CEIL)
    assert fresh is True
    assert reason == "fresh"


def test_late_run_past_tolerance_is_stale():
    now = _ANCHOR + timedelta(minutes=200)  # ~09:20 CST, 200 > 90
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=90, ceiling_cst=_CEIL)
    assert fresh is False
    assert "late" in reason


def test_run_past_absolute_ceiling_is_stale():
    now = _ANCHOR + timedelta(minutes=280)  # ~10:40 CST; big tolerance isolates ceiling
    fresh, reason = freshness_ok(now, _ANCHOR, tolerance_min=600, ceiling_cst=_CEIL)
    assert fresh is False
    assert "ceiling" in reason
