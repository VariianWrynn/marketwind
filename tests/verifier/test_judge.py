"""Tests for marketwind/verifier/judge.py — Tier-2 LLM judge checks."""

from __future__ import annotations

import pytest

from marketwind.verifier.judge import check_no_synthesis, check_no_contradiction
from marketwind.writer.domain import DraftClaim, DraftSentence, WriterOutput


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _output() -> WriterOutput:
    """Minimal WriterOutput for judge tests."""
    claims = [
        DraftClaim(local_id="c-001", statement="公司A净利润增长20%。", quote_ids=["q-1"]),
        DraftClaim(local_id="c-002", statement="公司A股价上涨5%。", quote_ids=["q-2"]),
    ]
    sentences = [
        DraftSentence(
            sentence="公司A净利润增长20%，带动股价上涨5%。",
            claim_ids=["c-001", "c-002"],
            source_ids=["s-1"],
            sentence_type="factual",
        )
    ]
    return WriterOutput(claims=claims, sentences=sentences)


# ---------------------------------------------------------------------------
# Fake judge helpers
# ---------------------------------------------------------------------------

async def _judge_flagged_synthesis(prompt: str) -> str:
    return '{"violations": [{"locus": "c-001", "detail": "两个断言被融合"}]}'


async def _judge_clean(prompt: str) -> str:
    return '{"violations": []}'


async def _judge_flagged_contradiction(prompt: str) -> str:
    return '{"violations": [{"locus": "c-002", "detail": "两条声明相互矛盾"}]}'


async def _judge_raises(prompt: str) -> str:
    raise RuntimeError("boom")


async def _judge_garbage(prompt: str) -> str:
    return "not json at all"


async def _judge_wrong_shape(prompt: str) -> str:
    return '{"oops": 1}'


# ---------------------------------------------------------------------------
# check_no_synthesis — I1
# ---------------------------------------------------------------------------

async def test_synthesis_flagged():
    violations = await check_no_synthesis(_output(), judge=_judge_flagged_synthesis)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "I1"
    assert v.locus == "c-001"
    assert "融合" in v.detail


async def test_synthesis_clean():
    violations = await check_no_synthesis(_output(), judge=_judge_clean)
    assert violations == []


async def test_synthesis_judge_raises_fail_closed():
    violations = await check_no_synthesis(_output(), judge=_judge_raises)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"


async def test_synthesis_garbage_fail_closed():
    violations = await check_no_synthesis(_output(), judge=_judge_garbage)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"


async def test_synthesis_wrong_shape_fail_closed():
    violations = await check_no_synthesis(_output(), judge=_judge_wrong_shape)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"


# ---------------------------------------------------------------------------
# check_no_contradiction — I10
# ---------------------------------------------------------------------------

async def test_contradiction_flagged():
    violations = await check_no_contradiction(_output(), judge=_judge_flagged_contradiction)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "I10"
    assert v.locus == "c-002"
    assert "矛盾" in v.detail


async def test_contradiction_clean():
    violations = await check_no_contradiction(_output(), judge=_judge_clean)
    assert violations == []


async def test_contradiction_judge_raises_fail_closed():
    violations = await check_no_contradiction(_output(), judge=_judge_raises)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"


async def test_contradiction_garbage_fail_closed():
    violations = await check_no_contradiction(_output(), judge=_judge_garbage)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"


async def test_contradiction_wrong_shape_fail_closed():
    violations = await check_no_contradiction(_output(), judge=_judge_wrong_shape)
    assert len(violations) == 1
    v = violations[0]
    assert v.check == "judge_unavailable"
