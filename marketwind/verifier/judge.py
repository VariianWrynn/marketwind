"""Tier-2 LLM judge checks for the Law-5 publication gate.

Checks I1 (synthesis) and I10 (contradiction) via an injected async judge seam.
FAIL CLOSED: any judge error / bad JSON yields Violation(check="judge_unavailable", ...).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from marketwind.verifier.domain import Violation
from marketwind.writer.domain import WriterOutput

# Type alias for the injected async judge seam (same pattern as Writer's `call`).
JudgeFn = Callable[[str], Awaitable[str]]


# ---------------------------------------------------------------------------
# Private helper: call judge, parse JSON, map to Violations. Fail closed.
# ---------------------------------------------------------------------------

async def _ask(prompt: str, *, judge: JudgeFn, check: str) -> list[Violation]:
    """Call the judge with *prompt* and return Violations for *check*.

    FAIL CLOSED: any exception, non-JSON reply, or wrong shape returns exactly
    one Violation(check="judge_unavailable", locus=<check code>, ...).
    """
    try:
        raw = await judge(prompt)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("response is not a JSON object")
        violations_raw = parsed["violations"]  # KeyError if missing
        if not isinstance(violations_raw, list):
            raise ValueError("violations is not a list")
        result: list[Violation] = []
        for entry in violations_raw:
            # Each entry must be a dict with "locus" and "detail" keys.
            locus = entry["locus"]
            detail = entry["detail"]
            result.append(Violation(check=check, locus=locus, detail=detail))
        return result
    except Exception as exc:  # noqa: BLE001 — intentionally broad; fail closed
        return [Violation(
            check="judge_unavailable",
            locus=check,
            detail=f"judge failed: {type(exc).__name__}: {exc}",
        )]


# ---------------------------------------------------------------------------
# Check I1 — RF-2: no sentence fuses two distinct claims into a combined
# assertion neither states alone.
# ---------------------------------------------------------------------------

async def check_no_synthesis(output: WriterOutput, *, judge: JudgeFn) -> list[Violation]:
    """Tier-2 check I1: no cross-claim synthesis in a single sentence.

    Instructs the judge to ONLY FLAG problems — never rewrite, never invent facts.
    Returns [] when clean, or Violation(check="I1", ...) per flagged locus.
    FAIL CLOSED on any judge/parse error: returns Violation(check="judge_unavailable").
    """
    claims_text = "\n".join(
        f"- {c.local_id}: {c.statement}" for c in output.claims
    )
    sentences_text = "\n".join(
        f"- sentence[{i}]: {s.sentence}"
        for i, s in enumerate(output.sentences)
    )
    prompt = (
        "你是一个金融报告核查员。你的唯一任务是检查以下句子是否将两个独立的断言融合为"
        "一个两者都没有单独声明过的组合断言（I1违规：跨断言合成）。\n\n"
        "【重要约束】\n"
        "- 只标记确实存在I1违规的条目，不要改写，不要生成任何事实，不要添加任何推断。\n"
        "- 如果没有问题，violations列表应为空。\n"
        "- 必须严格按照以下JSON格式回复，不得输出任何其他内容：\n"
        '{"violations": [{"locus": "<声明local_id或sentence索引>", "detail": "<简短中文原因>"}]}\n\n'
        "【待审查的声明列表】\n"
        f"{claims_text}\n\n"
        "【待审查的句子列表】\n"
        f"{sentences_text}"
    )
    return await _ask(prompt, judge=judge, check="I1")


# ---------------------------------------------------------------------------
# Check I10 — RF-7: no two claim statements assert contradictory facts.
# ---------------------------------------------------------------------------

async def check_no_contradiction(output: WriterOutput, *, judge: JudgeFn) -> list[Violation]:
    """Tier-2 check I10: no contradictory facts across claim statements.

    Instructs the judge to ONLY FLAG problems — never rewrite, never invent facts.
    Returns [] when clean, or Violation(check="I10", ...) per flagged locus.
    FAIL CLOSED on any judge/parse error: returns Violation(check="judge_unavailable").
    """
    claims_text = "\n".join(
        f"- {c.local_id}: {c.statement}" for c in output.claims
    )
    prompt = (
        "你是一个金融报告核查员。你的唯一任务是检查以下声明列表中是否存在相互矛盾的事实"
        "（I10违规：声明间事实矛盾）。\n\n"
        "【重要约束】\n"
        "- 只标记确实存在相互矛盾的条目，不要改写，不要生成任何事实，不要添加任何推断。\n"
        "- 如果没有问题，violations列表应为空。\n"
        "- 必须严格按照以下JSON格式回复，不得输出任何其他内容：\n"
        '{"violations": [{"locus": "<声明local_id>", "detail": "<简短中文原因>"}]}\n\n'
        "【待审查的声明列表】\n"
        f"{claims_text}"
    )
    return await _ask(prompt, judge=judge, check="I10")
