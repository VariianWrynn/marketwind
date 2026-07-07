# deploy/deadman-fc/tests/test_bark.py
from urllib.parse import quote

from watcher.config import Config
from watcher.bark import send_bark


def _cfg():
    return Config(
        oss_bucket="b", oss_endpoint="e", jobs=("premarket", "main"),
        period_seconds=86400, grace_seconds=10800,
        bark_base_url="https://api.day.app", bark_key="KEY",
    )


def test_send_bark_builds_expected_url_and_returns_true():
    calls = []
    ok = send_bark(_cfg(), "Title X", "Body Y", post=calls.append)
    assert ok is True
    assert calls == [f"https://api.day.app/KEY/{quote('Title X')}/{quote('Body Y')}"]


def test_send_bark_swallows_poster_error_and_returns_false():
    def boom(url):
        raise RuntimeError("network down")
    ok = send_bark(_cfg(), "t", "b", post=boom)
    assert ok is False
