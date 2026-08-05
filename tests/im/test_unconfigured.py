"""ADR-0005 option B: an unconfigured fallback slot must report failure, never ok."""
from marketwind.gateway.im.unconfigured import UnconfiguredSink


def test_send_reports_failure_naming_the_missing_setting():
    res = UnconfiguredSink("WECOM_WEBHOOK_URL").send("morning report body")
    assert res.ok is False
    assert "WECOM_WEBHOOK_URL" in res.error
