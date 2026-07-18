"""S4 — crowding / saturation d'edge."""
from __future__ import annotations

from hl_observer.signals.crowding import saturation


def test_saturation():
    assert saturation(10.0, 3.0)["sature"] is True      # 3 < 50% de 10
    assert saturation(10.0, 8.0)["sature"] is False
    assert saturation(-1.0, 5.0) is None                # pas d'edge de reference
