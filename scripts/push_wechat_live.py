"""One-shot live WeChat push through the real production path (gitignored).

Goes through build_channels(settings) -> run_pipeline with a floor-passing pool,
so it exercises exactly what the orchestrator will do in P2: grounded-floor gate
-> make_body -> apply_label (DEV prefix) -> send_with_fallback -> HermesWeixin
(hermes CLI). Prints the labeled message and the SendResult so a non-zero exit /
RuntimeError makes a failed delivery obvious.

Run:  PYTHONPATH=. PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/push_wechat_live.py
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from marketwind.config import settings
from marketwind.gateway.im.factory import build_channels
from marketwind.gateway.im.label import apply_label
from marketwind.gateway.im.stub import StubSink
from marketwind.orchestration.runner import run_pipeline
from marketwind.scout.domain import Quote, Source
from marketwind.scout.timeparse import CN_TZ


def _passing_sources() -> list[Source]:
    """8 grounded quotes / 1 primary / 2 outlets — clears the 8/1/2 floor."""
    now = datetime.now(UTC)

    def q(text: str, *, primary: str | None = None) -> Quote:
        return Quote(text=text, span_start=0, span_end=len(text),
                     context_before=None, context_after=None,
                     is_quantitative=False, attached_primary_url=primary)

    a = Source(url="https://a.example.cn/x", domain="a.example.cn", publish_ts=now,
               raw_content="...", byline="记者甲",
               quotes=[q(f"甲源引述 {i}") for i in range(4)])
    a.quotes[0] = q("甲源引述 0", primary="https://primary.gov.cn/doc")
    b = Source(url="https://b.example.cn/y", domain="b.example.cn", publish_ts=now,
               raw_content="...", byline="记者乙",
               quotes=[q(f"乙源引述 {i}") for i in range(4)])
    return [a, b]


async def main() -> None:
    live = settings.model_copy(update={"im_channel": "hermes_weixin"})
    primary, fallback = build_channels(live)
    stamp = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    body = f"MarketWind 实时推送测试 @ {stamp}（科创50盘前链路），收到请忽略本条。"

    async def make_body() -> str:
        return body

    print(f"[push] channel={live.im_channel} primary={type(primary).__name__} "
          f"fallback={type(fallback).__name__}")
    labeled = apply_label(body)
    print(f"[push] labeled message ({len(labeled)} chars):")
    print("       " + labeled)

    # ONE explicit live send via the real production channel, so a silent
    # stub-fallback cannot mask a failure and we don't fire a second rapid send
    # (the iLink channel is rate/session sensitive — see ADR-0001 / D-16).
    res = primary.send(labeled)
    print(f"[push] primary.send -> ok={res.ok} error={res.error!r}")
    if not res.ok:
        raise SystemExit(f"primary send FAILED: {res.error}")

    # Exercise the orchestrator gate path on STUBS (no extra live send): proves
    # the 8/1/2 floor passes and run_pipeline assembles+labels+routes correctly.
    sink = StubSink()
    await run_pipeline(
        sources=_passing_sources(), make_body=make_body,
        primary=sink, fallback=StubSink(),
        dev_channel=StubSink(), trace_id=f"live-push-{stamp}",
    )
    assert sink.sent and sink.sent[0].startswith("【DEV / UNVERIFIED"), sink.sent
    print(f"[push] run_pipeline (stub) routed a labeled brief: ok "
          f"({len(sink.sent[0])} chars, DEV-prefixed)")
    print("[push] OK — one real WeChat send delivered. "
          "Check WeChat for the 【DEV / UNVERIFIED …】 line.")


if __name__ == "__main__":
    asyncio.run(main())
