"""S6 — réserve de marge (jamais all-in)."""
from __future__ import annotations

import pytest

from hl_observer.risk.margin_reserve import capital_deployable, respecte_reserve


def test_deployable():
    assert capital_deployable(1000.0, reserve_frac=0.2) == pytest.approx(800.0)


def test_respecte_reserve():
    assert respecte_reserve(700.0, 1000.0, reserve_frac=0.2) is True
    assert respecte_reserve(900.0, 1000.0, reserve_frac=0.2) is False   # entame la reserve
