# tests/scheduling/test_entrypoint.py
from marketwind.scout.domain import FloorResult
from marketwind.scheduling.__main__ import build_parser, want_real_send, floor_line, floor_exit_code, want_scheduler


def _parse(argv):
    return build_parser().parse_args(argv)


def test_plain_run_sends_real():
    assert want_real_send(_parse([])) is True


def test_dry_run_never_sends_real():
    assert want_real_send(_parse(["--dry-run"])) is False


def test_force_calendar_implies_dry_run():
    # forcing the calendar without --send-real must NOT do a real send (#12).
    assert want_real_send(_parse(["--force-calendar"])) is False


def test_force_calendar_with_send_real_sends():
    assert want_real_send(_parse(["--force-calendar", "--send-real"])) is True


def test_dry_run_wins_over_send_real():
    assert want_real_send(_parse(["--send-real", "--dry-run"])) is False


def test_floor_only_flag_parses():
    assert _parse(["--floor-only"]).floor_only is True


def test_floor_line_reports_all_three_metrics():
    line = floor_line(FloorResult(grounded_quotes=9, primary_traced_quotes=2,
                                  independent_outlets=3, passed=True))
    assert "grounded=9" in line and "primary=2" in line
    assert "outlets=3" in line and "passed=True" in line


def test_exit_code_zero_on_pass_nonzero_on_subfloor():
    ok = FloorResult(grounded_quotes=9, primary_traced_quotes=2, independent_outlets=3, passed=True)
    bad = FloorResult(grounded_quotes=3, primary_traced_quotes=0, independent_outlets=1, passed=False)
    assert floor_exit_code(ok) == 0
    assert floor_exit_code(bad) != 0


def test_scheduler_flag_routes_to_daemon():
    assert want_scheduler(_parse(["--scheduler"])) is True


def test_absent_scheduler_flag_is_false():
    assert want_scheduler(_parse([])) is False
