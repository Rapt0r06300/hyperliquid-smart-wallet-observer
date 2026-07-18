"""Backtest carry sur funding historique — le funding s'accumule, le break-even arrive, PnL positif
si assez de funding ; le balayage trouve le meilleur levier."""
from __future__ import annotations

from hl_observer.backtesting.carry_historical_backtest import balayer_levier, simuler_carry


def test_funding_accumule_et_break_even():
    serie = [0.125] * 200                                  # 200 h à 0.125 bps/h = 25 bps
    r = simuler_carry("HYPE", serie, cout_entree_bps=11.0)
    assert abs(r.funding_cumule_bps - 25.0) < 1e-6
    assert r.break_even_h == 88                            # 11 / 0.125 = 88 h
    assert r.pnl_net_bps > 0 and r.positif is True


def test_pas_assez_de_funding_reste_negatif():
    r = simuler_carry("X", [0.125] * 10, cout_entree_bps=11.0)   # 10 h = 1.25 bps < 11
    assert r.positif is False and r.break_even_h is None


def test_balayage_trouve_meilleur_levier():
    serie = [0.2] * 300
    # levier haut = plus de notional = plus de frais -> le meilleur net dépend du coût
    res = balayer_levier("HYPE", serie, {1.0: 8.0, 2.0: 11.0, 5.0: 20.0})
    assert res["meilleur_levier"] == 1.0                  # coût le plus bas -> meilleur net ici
    assert res["meilleur_pnl_bps"] == max(res["par_levier"].values())
