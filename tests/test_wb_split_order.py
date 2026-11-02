"""Split rows must be ascending, criteria WC2–WC3 (docs/PLAN.md §4-52)."""

import pytest

from imquant import wb


@pytest.mark.parametrize("splits", [[20, 15], [18, 18], [12, 25, 22]])
def test_WC2_splits_out_of_order_are_refused(splits):
    names = [f"b{k}" for k in range(len(splits) + 1)]
    with pytest.raises(ValueError, match="out of order"):
        wb.Window(names, 10, 30, splits)


def test_WC2_ascending_splits_still_work():
    w = wb.Window(["a", "b", "c"], 10, 30, [15, 20])
    assert w.splits == [15, 20] and w.total_name == "a + b + c"


def test_WC3_codex_w7_case():
    with pytest.raises(ValueError):
        wb.Window(["a", "b", "c"], 10, 30, [20, 15])
