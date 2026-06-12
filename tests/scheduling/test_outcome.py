from marketwind.scheduling.outcome import (
    RunOutcome, PUBLISHED, SKIPPED_CALENDAR, SKIPPED_STALE,
    SUB_FLOOR, VERIFY_FAIL, MISSED, FAILED_INFRA,
)


def test_constants_are_the_seven_statuses():
    assert {PUBLISHED, SKIPPED_CALENDAR, SKIPPED_STALE, SUB_FLOOR,
            VERIFY_FAIL, MISSED, FAILED_INFRA} == {
        "published", "skipped_calendar", "skipped_stale", "sub_floor",
        "verify_fail", "missed", "failed_infra"}


def test_runoutcome_is_frozen_with_optional_detail():
    o = RunOutcome(status=PUBLISHED)
    assert o.status == "published" and o.detail is None
    o2 = RunOutcome(status=SUB_FLOOR, detail="x")
    assert o2.detail == "x"
