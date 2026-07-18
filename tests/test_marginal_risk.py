"""Risque portefeuille — netting inter-stratégies + capacité."""
from __future__ import annotations

from hl_observer.risk.marginal_risk import capacite_max_usd, exposition_nette


def test_netting_compense_les_sens_opposes():
    net = exposition_nette({"carry": {"HYPE": 500.0}, "liquidation": {"HYPE": -200.0, "BTC": 100.0}})
    assert net["HYPE"] == 300.0 and net["BTC"] == 100.0        # 500 - 200 = 300 net


def test_capacite():
    assert capacite_max_usd(None) is None                       # sans profondeur -> pas de devinette
    assert capacite_max_usd(100_000.0, impact_max_bps=20.0, pente_impact_bps_par_usd=0.001) == 20000.0
    assert capacite_max_usd(100_000.0) is not None              # repli prudent
