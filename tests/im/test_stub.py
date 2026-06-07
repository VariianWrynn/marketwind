"""StubSink: captures sent payloads; can be configured to fail."""
from marketwind.gateway.im.stub import StubSink


def test_stub_captures_message():
    sink = StubSink()
    result = sink.send("hello")
    assert result.ok is True
    assert sink.sent == ["hello"]


def test_stub_fail_mode_captures_nothing():
    sink = StubSink(fail=True)
    result = sink.send("hello")
    assert result.ok is False
    assert sink.sent == []


def test_stub_accumulates_multiple():
    sink = StubSink()
    sink.send("first")
    sink.send("second")
    assert sink.sent == ["first", "second"]
