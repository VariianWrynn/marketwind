"""Live DeepSeek judge seam for the Verifier Tier-2 checks. Smoke/live only."""
from __future__ import annotations


async def call_judge(prompt: str) -> str:  # pragma: no cover - live
    """Wrap the shared DeepSeek client as the judge seam: prompt string in,
    raw reply string out. Reuses writer.client.call_deepseek (no second client)."""
    from marketwind.writer.client import call_deepseek
    return await call_deepseek([{"role": "user", "content": prompt}])
