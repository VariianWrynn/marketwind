"""DEV/UNVERIFIED label + fail-closed length guard.

The caller reserves BODY_BUDGET when rendering (render_brief max_chars), so
apply_label only prepends. It NEVER truncates — truncation lives in render.py
(orphan-marker-safe). A body over budget is a caller bug -> raise (fail closed).
"""
from __future__ import annotations

DEV_PREFIX = "【DEV / UNVERIFIED — 非正式报告】"
MAX_TOTAL = 500
BODY_BUDGET = MAX_TOTAL - len(DEV_PREFIX)


def apply_label(body: str) -> str:
    labeled = DEV_PREFIX + body
    if len(labeled) > MAX_TOTAL:
        raise ValueError(
            f"labeled message length {len(labeled)} exceeds {MAX_TOTAL}; "
            f"render with max_chars=BODY_BUDGET ({BODY_BUDGET}) before labeling"
        )
    return labeled
