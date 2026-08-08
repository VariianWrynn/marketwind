"""Channel failover: primary fail -> fallback tried; both fail -> raise with trace_id."""
import pytest

from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import send_with_fallback


def test_primary_used_when_ok():
    primary, fallback = StubSink(), StubSink()
    send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1")
    assert primary.sent == ["hi"]
    assert fallback.sent == []


def test_fallback_used_when_primary_fails():
    primary, fallback = StubSink(fail=True), StubSink()
    send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1")
    assert primary.sent == []
    assert fallback.sent == ["hi"]


def test_both_fail_raises_with_trace_id():
    primary, fallback = StubSink(fail=True), StubSink(fail=True)
    with pytest.raises(RuntimeError, match="t1"):
        send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1")


def test_alert_fires_when_primary_fails():
    primary, fallback, alert = StubSink(fail=True), StubSink(), StubSink()
    send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1", alert=alert)
    assert len(alert.sent) == 1
    assert "failed" in alert.sent[0].lower()


def test_alert_not_fired_when_primary_succeeds():
    primary, fallback, alert = StubSink(), StubSink(), StubSink()
    send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1", alert=alert)
    assert alert.sent == []


def test_no_alert_is_safe():
    """alert=None (default) must not crash."""
    primary, fallback = StubSink(fail=True), StubSink()
    send_with_fallback("hi", primary=primary, fallback=fallback, trace_id="t1")
    assert fallback.sent == ["hi"]
