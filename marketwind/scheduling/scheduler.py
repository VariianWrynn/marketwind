"""In-memory dual-cron scheduler. Recompute fires on boot; no persistent store.
Generous misfire grace; freshness (run_once) is the real stale-guard."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from marketwind.scheduling.trigger import CronJob

_PREMARKET = CronJob(job_id="premarket", hour=18, minute=0, tz="America/New_York")
_MAIN = CronJob(job_id="main", hour=7, minute=0, tz="Asia/Shanghai")


def assert_timing_safe(*, misfire_grace_s: int, max_transient_retries: int,
                       backoff_ceiling_s: int, tolerance_min: int) -> None:
    """Fail loud at boot if a delayed+retried run could outlive its freshness
    tolerance. budget = misfire_grace + retries*backoff (seconds)."""
    budget_s = misfire_grace_s + max_transient_retries * backoff_ceiling_s
    if budget_s >= tolerance_min * 60:
        raise ValueError(
            f"timing budget {budget_s}s >= tolerance {tolerance_min*60}s — "
            "a delayed+retried run would be killed by freshness; "
            "lower misfire_grace_s/retries or raise tolerance"
        )


def build_scheduler(*, dispatch: Callable[[str], Awaitable[None]], misfire_grace_s: int) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    for job in (_PREMARKET, _MAIN):
        sched.add_job(dispatch, args=[job.job_id], trigger=job.to_apscheduler(),
                      id=job.job_id, misfire_grace_time=misfire_grace_s,
                      max_instances=1, coalesce=True)
    return sched
