from datetime import datetime, time, timezone
from marketwind.scheduling.dispatch import resolve_job, JobPlan
from marketwind.scout.timeparse import CN_TZ

_NOW = datetime(2026, 6, 9, 22, 30, tzinfo=timezone.utc)   # 06:30 CST 2026-06-10
_CEIL = time(10, 0)


def test_main_uses_its_own_0700_cst_anchor_and_tolerance():
    plan = resolve_job("main", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
    assert isinstance(plan, JobPlan)
    assert plan.job_id == "main"
    assert plan.tolerance_min == 45                       # main's OWN tolerance, not premarket's
    assert plan.trading_date == _NOW.astimezone(CN_TZ).date()
    # 07:00 CST anchor on the trading date:
    assert plan.anchor.astimezone(CN_TZ).hour == 7 and plan.anchor.astimezone(CN_TZ).minute == 0


def test_premarket_uses_et_anchor_and_premarket_tolerance():
    plan = resolve_job("premarket", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
    assert plan.tolerance_min == 90
    # 18:00 America/New_York anchor (US close + reporting offset), per existing premarket behavior:
    from zoneinfo import ZoneInfo
    assert plan.anchor.astimezone(ZoneInfo("America/New_York")).hour == 18


def test_unknown_job_raises():
    import pytest
    with pytest.raises(ValueError):
        resolve_job("nope", _NOW, premarket_tol_min=90, main_tol_min=45, ceiling_cst=_CEIL)
