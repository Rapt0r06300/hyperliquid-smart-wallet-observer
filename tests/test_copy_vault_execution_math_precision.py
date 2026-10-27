from __future__ import annotations

import math

from hl_observer.backtesting.copy_vault_execution_math import (
    _book_side,
    _walk_base_quantity,
    _walk_quote_notional,
)


def test_book_side_requires_exact_binding_to_recorded_bbo() -> None:
    assert _book_side(
        {"asks5": [[100.0000000000005, 1.0]]},
        "asks5",
        expected_best=100.0,
        descending=False,
    ) is None


def test_quote_walk_rejects_one_ulp_of_unobserved_depth() -> None:
    target = math.nextafter(0.3, math.inf)

    assert _walk_quote_notional([(1.0, 0.3)], target) is None


def test_base_walk_rejects_one_ulp_of_unobserved_depth() -> None:
    target = math.nextafter(0.3, math.inf)

    assert _walk_base_quantity([(1.0, 0.3)], target) is None
