# deploy/deadman-fc/tests/test_ping_handler.py
from datetime import datetime, timezone

from watcher.config import Config
from watcher.state import read_state, State
from watcher.ping_handler import process_ping


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


def _cfg():
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=("premarket", "main"),
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


NOW = datetime(2026, 7, 7, 5, 0, tzinfo=timezone.utc)


def test_valid_job_writes_and_returns_200():
    s = FakeStore()
    code = process_ping(s, _cfg(), "premarket", NOW)
    assert code == 200
    assert read_state(s, "premarket") == State(last_ping=NOW, alerted=False)


def test_unknown_job_returns_400_and_writes_nothing():
    s = FakeStore()
    code = process_ping(s, _cfg(), "bogus", NOW)
    assert code == 400
    assert s.objects == {}


def test_missing_job_returns_400_and_writes_nothing():
    s = FakeStore()
    code = process_ping(s, _cfg(), None, NOW)
    assert code == 400
    assert s.objects == {}
