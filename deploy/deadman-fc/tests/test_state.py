# deploy/deadman-fc/tests/test_state.py
from datetime import datetime, timezone

from watcher.state import State, read_state, put_ping, mark_alerted


class FakeStore:
    def __init__(self):
        self.objects = {}
    def get(self, key):
        return self.objects.get(key)
    def put(self, key, data):
        self.objects[key] = data


NOW = datetime(2026, 7, 7, 5, 0, tzinfo=timezone.utc)


def test_put_ping_then_read_round_trips():
    s = FakeStore()
    put_ping(s, "premarket", NOW)
    assert "state/premarket.json" in s.objects
    assert read_state(s, "premarket") == State(last_ping=NOW, alerted=False)


def test_read_state_missing_returns_none():
    assert read_state(FakeStore(), "premarket") is None


def test_mark_alerted_sets_flag_preserving_last_ping():
    s = FakeStore()
    put_ping(s, "main", NOW)
    mark_alerted(s, "main")
    assert read_state(s, "main") == State(last_ping=NOW, alerted=True)
