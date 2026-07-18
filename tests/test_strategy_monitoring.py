"""P2/P3/P4 — anomalies, désactivation auto, registre de cycle de vie."""
from __future__ import annotations

import pytest

from hl_observer.ops.strategy_monitoring import anomalies, doit_desactiver, RegistreStrategies


def test_anomalies():
    assert anomalies(drawdown=50.0, drawdown_max=100.0) == []
    assert "DRAWDOWN_SEUIL" in anomalies(drawdown=120.0, drawdown_max=100.0)
    assert "DIVERGENCE_SOURCES" in anomalies(sources_sures=False)


def test_desactiver_zombie():
    assert doit_desactiver(2.0, 10.0, fraction=0.4) is True     # 2 < 4 -> decroche
    assert doit_desactiver(8.0, 10.0, fraction=0.4) is False
    assert doit_desactiver(None, 10.0) is True                  # edge inconnu -> observation


def test_registre_cycle_de_vie():
    r = RegistreStrategies()
    r.promouvoir("carry", "PAPER")
    r.promouvoir("mm", "RETRAITE")
    assert r.actives() == ["carry"]
    with pytest.raises(ValueError):
        r.promouvoir("x", "MAINNET")                            # etape inconnue -> refus
