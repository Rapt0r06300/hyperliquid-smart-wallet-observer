"""#50 — CRITÈRE D'ARRÊT : décidé à froid, il tranche VALIDE / A_POURSUIVRE / ARRETER."""
from __future__ import annotations

from hl_observer.ops.critere_arret import evaluer


def test_pas_assez_de_donnees_on_poursuit():
    v = evaluer(jours_ecoules=3.0, pnl_net_usd=-1.0, n_trades=4, capital_usd=1000.0)
    assert v.verdict == "A_POURSUIVRE" and "pas encore assez" in v.raison


def test_positif_et_bat_le_passif_VALIDE():
    # 30 j, +20$ sur 1000$ ; passif 2% APR sur 30 j = ~1.64$ -> on bat largement
    v = evaluer(jours_ecoules=30.0, pnl_net_usd=20.0, n_trades=50, capital_usd=1000.0)
    assert v.verdict == "VALIDE" and v.bat_le_passif is True


def test_negatif_ARRETER():
    v = evaluer(jours_ecoules=30.0, pnl_net_usd=-5.0, n_trades=50, capital_usd=1000.0)
    assert v.verdict == "ARRETER" and "PnL net <= 0" in v.raison


def test_positif_mais_DOMINE_par_le_passif_ARRETER():
    # +0.50$ sur 30 j alors qu'un simple depot aurait rendu ~1.64$ -> on n'ajoute RIEN
    v = evaluer(jours_ecoules=30.0, pnl_net_usd=0.5, n_trades=50, capital_usd=1000.0)
    assert v.verdict == "ARRETER" and "DOMINE" in v.raison
