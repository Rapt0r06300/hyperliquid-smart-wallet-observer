"""LE SNIPER N'ENTRE PAS AU PRIX DU LEADER (2026-07-11) — pistes 61-70.

LE BUG LE PLUS INSIDIEUX, ET LE PLUS FLATTEUR.

Le paper trade entrait au prix du leader, sans coût de copie. Résultat mesuré : **dans 8 cas sur
20, le bot entrait à un prix MEILLEUR que le marché** — ce qui est physiquement impossible. Le
backtest ne mentait pas un peu : il fabriquait de l'edge à partir de rien.

Trois vérités doivent tenir, et elles sont ici verrouillées :

  1. on entre au **mid COURANT**, pas au prix qu'avait le leader il y a 57 secondes ;
  2. le fill est toujours **DÉFAVORABLE** — on achète au-dessus du mid, on vend en dessous ;
  3. **la latence COÛTE** : copier un signal vieux de 60 s coûte plus cher que copier un signal
     frais. Un modèle où l'attente est gratuite promet un edge qui n'existe pas.

Simulation paper uniquement. Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.exec_model import simulate_execution


def _fill(side: str, *, latence_s: float = 0.0, mid: float = 100.0) -> float:
    return simulate_execution(
        side=side, notional_usdc=500.0, mid_price=mid,
        top_depth_usdc=1_000_000.0, latency_sec=latence_s,
    ).fill_price


# ------------------------------------------------------- le fill est TOUJOURS défavorable

def test_a_buy_never_fills_below_the_mid():
    """LE TEST QUI AURAIT TOUT ATTRAPÉ. Entrer sous le mid en achetant, c'est de l'argent gratuit :
    ça n'existe pas, et un backtest qui l'autorise fabrique un edge fictif."""
    assert _fill("BUY") > 100.0


def test_a_sell_never_fills_above_the_mid():
    assert _fill("SELL") < 100.0


def test_the_cost_is_symmetric_between_the_two_sides():
    """Un coût asymétrique biaiserait le bot vers un côté — et 97 % de la perte venait des shorts."""
    cout_achat = _fill("BUY") - 100.0
    cout_vente = 100.0 - _fill("SELL")
    assert cout_achat == pytest.approx(cout_vente, rel=1e-6)


# ------------------------------------------------------- la latence COÛTE

def test_copying_a_stale_signal_costs_more_than_a_fresh_one():
    """LE CŒUR DU SNIPER. Un signal vieux de 60 s ne peut pas coûter le même prix qu'un signal
    instantané : sinon, attendre serait gratuit, et la fraîcheur n'aurait aucune valeur."""
    frais = _fill("BUY", latence_s=0.0)
    vieux = _fill("BUY", latence_s=60.0)
    assert vieux > frais, "la latence est gratuite : le modèle promet un edge qui n'existe pas"


def test_the_latency_cost_grows_with_the_delay():
    couts = [_fill("BUY", latence_s=t) for t in (0.0, 5.0, 30.0, 60.0)]
    assert couts == sorted(couts), "le coût de copie doit croître avec le retard"


def test_the_latency_cost_is_capped_not_infinite():
    """Un signal très vieux est REFUSÉ par les gates de fraîcheur ; le coût ne doit pas exploser
    au point de rendre le modèle absurde. On borne, sans jamais annuler."""
    tres_vieux = _fill("BUY", latence_s=3600.0)
    assert tres_vieux > _fill("BUY", latence_s=60.0)
    assert (tres_vieux - 100.0) / 100.0 * 10_000.0 < 100.0, "le coût de latence n'est pas borné"


# ------------------------------------------------------- la taille compte

def test_a_bigger_order_pays_more_impact():
    """Sur un carnet fin, une grosse taille paie davantage. Ignorer ça flatte les gros trades."""
    petit = simulate_execution(side="BUY", notional_usdc=100.0, mid_price=100.0,
                               top_depth_usdc=5_000.0).net_cost_bps
    gros = simulate_execution(side="BUY", notional_usdc=50_000.0, mid_price=100.0,
                              top_depth_usdc=5_000.0).net_cost_bps
    assert gros > petit


def test_a_thin_book_costs_more_than_a_deep_one():
    epais = simulate_execution(side="BUY", notional_usdc=1_000.0, mid_price=100.0,
                               top_depth_usdc=1_000_000.0).net_cost_bps
    fin = simulate_execution(side="BUY", notional_usdc=1_000.0, mid_price=100.0,
                             top_depth_usdc=2_000.0).net_cost_bps
    assert fin > epais


# ------------------------------------------------------- honnêteté du modèle

def test_the_execution_cost_is_never_negative():
    """RÈGLE DURE : être PAYÉ pour entrer n'existe pas au tarif de base. C'était le bug du
    « rebate maker » — un coût négatif fabriquait de l'edge à partir de rien."""
    for side in ("BUY", "SELL"):
        for maker in (False, True):
            r = simulate_execution(side=side, notional_usdc=500.0, mid_price=100.0,
                                   top_depth_usdc=1_000_000.0, is_maker=maker)
            assert r.net_cost_bps > 0.0, f"coût négatif ({side}, maker={maker}) : edge fabriqué"
