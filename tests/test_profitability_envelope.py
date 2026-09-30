"""[CROSS-VENUE #1] profitability envelope : entrer à la cible, tenir au-dessus du min, annuler hors bande."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pytest  # noqa: E402

from hl_observer.arbitrage import profitability_envelope as PE   # noqa: E402


def test_envelope_actions_selon_la_bande():
    env = PE.EnveloppeProfitabilite(min_net_edge_bps=5.0, target_net_edge_bps=15.0, max_net_edge_bps=100.0)
    assert env.action(20.0)["action"] == PE.ENTER           # >= cible -> on entre
    assert env.action(8.0)["action"] == PE.HOLD             # dans [min, target) -> on maintient, on n'ajoute pas
    assert env.action(3.0)["action"] == PE.REJECT_TROP_FAIBLE   # sous le plancher -> on n'entre pas
    assert env.action(3.0, en_position=True)["action"] == PE.CANCEL   # déjà en position + edge parti -> on annule
    assert env.action(150.0)["action"] == PE.REJECT_ANOMALIE    # trop beau (carnet croisé / stale) -> non tradé
    assert env.action("UNMEASURABLE")["action"] == PE.REJECT_UNMEASURABLE


def test_envelope_dans_la_bande_et_validation():
    env = PE.EnveloppeProfitabilite(min_net_edge_bps=5.0, target_net_edge_bps=15.0, max_net_edge_bps=100.0)
    assert env.dans_la_bande(20.0) is True and env.dans_la_bande(150.0) is False and env.dans_la_bande(3.0) is False
    with pytest.raises(ValueError):
        PE.EnveloppeProfitabilite(min_net_edge_bps=20.0, target_net_edge_bps=10.0, max_net_edge_bps=100.0)  # min>target
