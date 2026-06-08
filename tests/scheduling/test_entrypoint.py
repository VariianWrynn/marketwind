# tests/scheduling/test_entrypoint.py
from marketwind.scheduling.__main__ import build_parser, want_real_send


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
