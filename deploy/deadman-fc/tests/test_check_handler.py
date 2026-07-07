# deploy/deadman-fc/tests/test_check_handler.py
from datetime import datetime, timedelta, timezone

from watcher.config import Config
from watcher.state import put_ping, mark_alerted, read_state
from watcher.check_handler import run_check


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


def _cfg(jobs=("premarket", "main")):
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=jobs,
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
OVERDUE = NOW - timedelta(days=1, hours=4)   # past period(1d)+grace(3h)
FRESH = NOW - timedelta(hours=2)             # well inside the deadline


def _recorder(result=True):
    calls = []
    def bark(cfg, title, body):
        calls.append((title, body))
        return result
    return bark, calls


def test_overdue_not_alerted_pages_once_and_marks():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == ["premarket"]
    assert len(calls) == 1
    assert read_state(s, "premarket").alerted is True


def test_overdue_already_alerted_does_not_page():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    mark_alerted(s, "premarket")
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_within_deadline_does_not_page():
    s = FakeStore()
    put_ping(s, "premarket", FRESH)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_not_armed_does_not_page():
    s = FakeStore()  # never pinged
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert calls == []


def test_only_overdue_job_pages_when_other_is_healthy():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    put_ping(s, "main", FRESH)
    bark, calls = _recorder(True)
    paged = run_check(s, _cfg(("premarket", "main")), NOW, bark=bark)
    assert paged == ["premarket"]


def test_bark_failure_leaves_unalerted_for_retry():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    bark, calls = _recorder(False)   # delivery failed
    paged = run_check(s, _cfg(("premarket",)), NOW, bark=bark)
    assert paged == []
    assert read_state(s, "premarket").alerted is False


def test_one_job_exception_does_not_block_the_other():
    s = FakeStore()
    put_ping(s, "premarket", OVERDUE)
    put_ping(s, "main", OVERDUE)
    def bark(cfg, title, body):
        if "premarket" in title:
            raise RuntimeError("boom")
        return True
    paged = run_check(s, _cfg(("premarket", "main")), NOW, bark=bark)
    assert paged == ["main"]
