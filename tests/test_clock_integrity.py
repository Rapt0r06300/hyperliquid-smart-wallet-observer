"""S1 — intégrité temporelle : skew + ordering monotone."""
from __future__ import annotations

from hl_observer.ops.clock_integrity import skew_excessif, GardeMonotone


def test_skew():
    assert skew_excessif(1000.0, 1000.0, max_skew_ms=2000.0) is False
    assert skew_excessif(1000.0, 5000.0, max_skew_ms=2000.0) is True
    assert skew_excessif("x", 1.0) is True


def test_garde_monotone_rejette_hors_ordre():
    g = GardeMonotone()
    assert g.accepter(100) is True
    assert g.accepter(200) is True
    assert g.accepter(150) is False        # recule -> rejete
    assert g.accepter(200) is True         # egal ok
