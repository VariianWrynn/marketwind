# tests/scheduling/test_trigger.py
from datetime import datetime
from zoneinfo import ZoneInfo

from marketwind.scheduling.trigger import CronJob


def test_cronjob_to_apscheduler_computes_next_fire():
    # Pre-market cron at 18:00 America/New_York. From 17:00 ET, next fire is 18:00 ET.
    job = CronJob(job_id="premarket", hour=18, minute=0, tz="America/New_York")
    trig = job.to_apscheduler()
    ny = ZoneInfo("America/New_York")
    prev = datetime(2026, 6, 8, 17, 0, tzinfo=ny)
    nxt = trig.get_next_fire_time(None, prev)
    assert nxt.hour == 18 and nxt.minute == 0
    assert nxt.tzinfo is not None and nxt.utcoffset() == prev.utcoffset()  # same ET day
