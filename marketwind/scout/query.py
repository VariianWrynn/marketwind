"""Bocha query construction for the 昨日复盘 dimension. Hard date anchors only."""

from __future__ import annotations

from datetime import date


def build_recap_queries(prev_session: date) -> list[str]:
    anchor = f"{prev_session.month}月{prev_session.day}日"
    return [
        f"科创50 {anchor} 收盘 复盘",
        f"科创50指数 上一交易日 涨跌幅 成交额",
        f"科创板 权重股 {anchor} 表现",
        f"科创50 成份股 {anchor} 业绩",
        f"科创板 {anchor} 定增 募资 公告",
        f"科创板 {anchor} 首发 IPO 新股",
    ]
