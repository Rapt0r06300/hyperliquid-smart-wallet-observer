"""INVARIANTS COMPTABLES DU PnL PAPER (chasse aux bugs, 2026-07-11).

Un PnL faux est pire qu'un PnL mauvais : il rend toute decision suivante absurde.
Ces tests figent les proprietes qui DOIVENT etre vraies, quoi qu'il arrive.

Verifie sur le ledger reel du run des 09-10 juillet :
  - net == gross - frais            : 24/24 evenements coherents  OK
  - realized == somme des sorties   : ecart 0,000000 $            OK
  - frais d'entree non deduits du PnL : **ce n'est PAS un bug** -- ils sont deja INCLUS dans le
    prix d'entree (`simulate_execution` renvoie un fill "tout compris"). Les soustraire une
    seconde fois les compterait DOUBLE. Le test ci-dessous verrouille cette regle, car c'est
    exactement le genre de "correction" qui casse un PnL.

Simulation paper uniquement. Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution


def _fill(side: str, mid: float, latency_sec: float = 0.0) -> tuple[float, float]:
    r = simulate_execution(side=side, notional_usdc=500, mid_price=mid, top_depth_usdc=50_000,
                           latency_sec=latency_sec, config=ExecModelConfig())
    return r.fill_price, r.net_cost_bps


def test_entry_costs_live_inside_the_entry_price_not_beside_it():
    """Les couts d'entree sont DANS le prix de fill. Les soustraire en plus = double comptage."""
    mid = 100.0
    fill, cost = _fill("LONG", mid, latency_sec=57.0)
    ecart_bps = (fill - mid) / mid * 10_000
    assert ecart_bps == pytest.approx(cost, abs=1e-6), (
        "le prix de fill doit incorporer EXACTEMENT le cout net. S'il ne le fait pas, quelqu'un "
        "devra soustraire les couts ailleurs -- et un jour on le fera deux fois."
    )


def test_a_round_trip_at_a_flat_price_loses_exactly_the_costs():
    """INVARIANT FONDAMENTAL : a prix INCHANGE, un aller-retour perd les couts. Ni plus, ni moins.

    C'est le test qui attrape le double comptage ET la sous-facturation d'un seul coup.
    """
    mid = 100.0
    entree, cout_e = _fill("LONG", mid, latency_sec=57.0)     # on achete plus cher
    sortie, cout_s = _fill("SELL", mid, latency_sec=0.0)      # on revend moins cher

    # PnL d'un aller-retour a prix inchange, en bps du notionnel
    pnl_bps = (sortie - entree) / entree * 10_000
    attendu = -(cout_e + cout_s)
    assert pnl_bps == pytest.approx(attendu, rel=0.02), (
        f"aller-retour a prix constant : {pnl_bps:.2f} bps, attendu {attendu:.2f} bps "
        f"(= -(cout entree {cout_e:.2f} + cout sortie {cout_s:.2f})). "
        f"Un ecart signale un double comptage ou une fuite de couts."
    )
    assert pnl_bps < 0, "un aller-retour a prix constant DOIT perdre de l'argent"


def test_long_and_short_are_symmetric():
    """Le PnL doit etre symetrique : aucun biais cache en faveur d'un sens."""
    mid = 100.0
    l_fill, l_cost = _fill("LONG", mid, latency_sec=30.0)
    s_fill, s_cost = _fill("SHORT", mid, latency_sec=30.0)
    assert l_cost == pytest.approx(s_cost, abs=1e-9), "les couts doivent etre identiques long/short"
    # le LONG paie AU-DESSUS du mid, le SHORT vend AU-DESSOUS -- du meme montant
    assert (l_fill - mid) == pytest.approx(mid - s_fill, rel=1e-6), (
        "asymetrie long/short dans le prix de fill : un sens serait avantage"
    )


def test_costs_never_turn_negative_for_a_taker():
    """Un ordre au marche ne peut pas RAPPORTER de l'argent a l'execution. Jamais."""
    for lat in (0.0, 5.0, 57.0, 600.0):
        _, cost = _fill("LONG", 100.0, latency_sec=lat)
        assert cost > 0, f"cout taker negatif ({cost:.2f} bps) a {lat} s : le bot serait paye pour entrer"


def test_a_slower_copy_is_always_more_expensive():
    """MONOTONIE : plus on copie tard, plus ca coute. Sinon la fraicheur ne vaut rien."""
    couts = [_fill("LONG", 100.0, latency_sec=t)[1] for t in (0.0, 10.0, 30.0, 57.0)]
    assert couts == sorted(couts), f"le cout n'augmente pas avec le retard : {couts}"
    assert couts[-1] > couts[0], "copier avec 57 s de retard coute autant qu'instantanement ?!"
