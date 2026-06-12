# tests/scheduling/test_scheduler.py
import pytest

from marketwind.scheduling.scheduler import assert_timing_safe, build_scheduler


def test_timing_safe_passes_with_default_budget():
    # grace 900s (15m) + retries 2*30s (1m) = 16m < 90m tolerance -> OK, no raise.
    assert_timing_safe(misfire_grace_s=900, max_transient_retries=2,
                       backoff_ceiling_s=30, tolerance_min=90)


def test_timing_unsafe_grace_exceeds_tolerance_raises():
    # grace 2h (7200s) alone blows past the 90m tolerance -> must fail loud.
    with pytest.raises(ValueError, match="timing budget"):
        assert_timing_safe(misfire_grace_s=7200, max_transient_retries=2,
                           backoff_ceiling_s=30, tolerance_min=90)


def test_build_scheduler_registers_two_jobs_with_grace():
    async def _job(job_id):
        return None
    sched = build_scheduler(dispatch=_job, misfire_grace_s=900)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"premarket", "main"}
    assert jobs["premarket"].misfire_grace_time == 900
    assert jobs["main"].misfire_grace_time == 900


def test_each_job_registered_with_its_own_job_id():
    seen = []
    async def _dispatch(job_id):
        seen.append(job_id)
    sched = build_scheduler(dispatch=_dispatch, misfire_grace_s=900)
    jobs = sched.get_jobs()
    assert {j.id for j in jobs} == {"premarket", "main"}
    # each job carries its own job_id as the first positional arg:
    assert {j.args[0] for j in jobs} == {"premarket", "main"}
