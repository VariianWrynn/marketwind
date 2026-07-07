# tests/scheduling/test_config_p2a.py
from marketwind.config import Settings


def _settings() -> Settings:
    # database_url / redis_url are required; supply throwaway values.
    return Settings(database_url="postgres://x", redis_url="redis://x")


def test_p2a_defaults_present_and_correct():
    s = _settings()
    assert s.misfire_grace_s == 900
    assert s.max_transient_retries == 2
    assert s.backoff_ceiling_s == 30
    assert s.premarket_tolerance_min == 90
    assert s.main_tolerance_min == 90
    assert s.freshness_ceiling_cst == "10:00"
    assert s.main_report_time_cst == "07:00"


def test_healthcheck_urls_default_empty():
    s = _settings()
    assert s.healthcheck_url_premarket == ""
    assert s.healthcheck_url_main == ""
