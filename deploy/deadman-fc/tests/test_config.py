# deploy/deadman-fc/tests/test_config.py
from watcher.config import Config, load


def test_load_reads_full_env():
    cfg = load({
        "OSS_BUCKET": "mw-deadman",
        "OSS_ENDPOINT": "oss-cn-hangzhou-internal.aliyuncs.com",
        "JOBS": "premarket,main",
        "PERIOD_SECONDS": "3600",
        "GRACE_SECONDS": "600",
        "BARK_BASE_URL": "https://api.day.app",
        "BARK_KEY": "abc123",
    })
    assert cfg == Config(
        oss_bucket="mw-deadman",
        oss_endpoint="oss-cn-hangzhou-internal.aliyuncs.com",
        jobs=("premarket", "main"),
        period_seconds=3600,
        grace_seconds=600,
        bark_base_url="https://api.day.app",
        bark_key="abc123",
    )


def test_load_applies_defaults():
    cfg = load({})
    assert cfg.jobs == ("premarket", "main")
    assert cfg.period_seconds == 86400
    assert cfg.grace_seconds == 10800
    assert cfg.oss_bucket == ""
    assert cfg.bark_key == ""
