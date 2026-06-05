"""apply_label: hard-prefix + fail-closed <=500 guard; never truncates."""
import pytest

from marketwind.gateway.im.label import (
    DEV_PREFIX, MAX_TOTAL, BODY_BUDGET, apply_label,
)


def test_prefix_is_prepended():
    out = apply_label("科创50昨日收涨0.36%。[1]")
    assert out.startswith(DEV_PREFIX)
    assert "科创50昨日收涨0.36%。[1]" in out


def test_budget_is_total_minus_prefix():
    assert BODY_BUDGET == MAX_TOTAL - len(DEV_PREFIX)


def test_body_at_budget_fits_total():
    body = "字" * BODY_BUDGET
    out = apply_label(body)
    assert len(out) == MAX_TOTAL


def test_overlong_body_raises_not_truncates():
    # A body exceeding the reserved budget is a caller bug; fail closed.
    with pytest.raises(ValueError, match="exceeds"):
        apply_label("字" * (BODY_BUDGET + 1))
