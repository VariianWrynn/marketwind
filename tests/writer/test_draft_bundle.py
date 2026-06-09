"""Offline unit tests for DraftBundle / draft_report deferral invariant.

No real DB needed — load_pool and persist_report are monkeypatched.
"""

from __future__ import annotations

import json

import pytest

from marketwind.writer.domain import (
    DraftBundle,
    PooledQuote,
    PooledSource,
)
from marketwind.writer.runner import draft_report

# ---------------------------------------------------------------------------
# Canned pool — one source, two quotes (mirrors POOL in test_writer.py)
# ---------------------------------------------------------------------------
_RAW = "科创50收涨0.36%。市场情绪偏谨慎。"
_CANNED_POOL = [
    PooledSource(
        "SRC-A",
        "https://m.cls.cn/a/1",
        "m.cls.cn",
        False,
        [
            PooledQuote(
                "QUO-1",
                "科创50收涨0.36%。",
                True,
                "data",
                "https://cninfo.com.cn/x",
                span_start=0,
                span_end=len("科创50收涨0.36%。"),
            ),
            PooledQuote(
                "QUO-2",
                "市场情绪偏谨慎。",
                False,
                "factual",
                None,
                span_start=len("科创50收涨0.36%。"),
                span_end=len(_RAW),
            ),
        ],
        raw_content=_RAW,
    ),
]

# ---------------------------------------------------------------------------
# Stub LLM call — returns JSON consistent with alias scheme (s1 / q1, q2)
# ---------------------------------------------------------------------------
_STUB_CONTENT = json.dumps({
    "claims": [
        {"id": "c-001", "statement": "科创50上一交易日收涨0.36%", "quote_ids": ["q1"]},
    ],
    "sentences": [
        {
            "sentence": "科创50上一交易日收涨0.36%。",
            "claim_ids": ["c-001"],
            "source_ids": ["s1"],
            "sentence_type": "factual",
        },
    ],
})


async def _stub_call(messages):
    return _STUB_CONTENT


# ---------------------------------------------------------------------------
# Spy for persist_report
# ---------------------------------------------------------------------------
class _PersistSpy:
    def __init__(self):
        self.calls = 0

    async def __call__(self, conn, claims, sentences):
        self.calls += 1
        return "report-123"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_draft_report_defers_persistence(monkeypatch):
    """persist_report must NOT be called inside draft_report — only on commit()."""
    spy = _PersistSpy()

    async def fake_load_pool(conn):
        return _CANNED_POOL

    monkeypatch.setattr("marketwind.writer.runner.load_pool", fake_load_pool)
    monkeypatch.setattr("marketwind.writer.runner.persist_report", spy)

    dummy_conn = object()
    bundle = await draft_report(dummy_conn, call=_stub_call)

    # KEY assertion: persist has NOT been called yet
    assert spy.calls == 0, (
        f"persist_report was called {spy.calls} time(s) inside draft_report — "
        "it must be deferred to commit()"
    )

    # body should be a non-empty rendered string
    assert isinstance(bundle.body, str) and len(bundle.body) > 0

    # Now commit — persist fires exactly once and returns the fake report_id
    report_id = await bundle.commit()
    assert spy.calls == 1
    assert report_id == "report-123"


async def test_bundle_carries_output_and_pool(monkeypatch):
    """DraftBundle must carry the assembled WriterOutput and the loaded pool."""
    spy = _PersistSpy()

    async def fake_load_pool(conn):
        return _CANNED_POOL

    monkeypatch.setattr("marketwind.writer.runner.load_pool", fake_load_pool)
    monkeypatch.setattr("marketwind.writer.runner.persist_report", spy)

    dummy_conn = object()
    bundle = await draft_report(dummy_conn, call=_stub_call)

    # pool identity
    assert bundle.pool is _CANNED_POOL
    assert len(bundle.pool) == 1

    # output is a WriterOutput with our claim
    assert bundle.output.claims[0].local_id == "c-001"
    assert bundle.output.claims[0].quote_ids == ["QUO-1"]  # alias resolved
