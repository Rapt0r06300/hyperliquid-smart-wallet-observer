"""LE COÛT D'ENTRÉE NE DOIT ÊTRE COMPTÉ QU'UNE FOIS (2026-07-11).

HISTOIRE VRAIE, ET C'EST MOI QUI AI EU TORT.

Mon audit forensique calculait `net = brut − (frais_entrée + frais_sortie)` et concluait :
« bug comptable : les frais d'entrée ne sont déduits nulle part ». **C'était faux.**

Le prix d'entrée stocké EST le prix de fill : `paper_engine.py` pose
`entry_price = exec_result.fill_price`, et le déclare noir sur blanc
(`embedded_cost_model = "fill_price_includes_spread_slippage_fee_latency"`).
Le coût d'entrée est donc DÉJÀ dans le prix — il dégrade le brut. Le champ `fee_cost_usdc` de
l'événement OPEN n'est qu'un **report** de ce coût, pas une seconde ponction : le bot ne débite
jamais `realized` à l'ouverture, et `status_routes` passe déjà `fees_paid_usdc=0.0` à la
réconciliation, précisément « to avoid subtracting them twice ».

Le soustraire une deuxième fois **noircissait** le PnL de 0,50 $ sur 10 trades.
**Noircir un PnL est aussi malhonnête que le flatter.**

Ces tests verrouillent l'invariant dans les deux sens, pour que ni moi ni personne ne
re-« corrige » ce faux bug.

Simulation paper uniquement. Aucun ordre réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from analyze_trading_pnl import build_round_trips  # noqa: E402

from hl_observer.paper_trading.exec_model import simulate_execution  # noqa: E402


# ---------------------------------------------------------- le prix de fill EMBARQUE le coût

def test_the_fill_price_is_worse_than_the_mid_by_the_cost():
    """C'est TOUT le raisonnement : si le fill était au mid, le coût serait perdu."""
    r = simulate_execution(side="BUY", notional_usdc=500.0, mid_price=100.0,
                           top_depth_usdc=1_000_000.0)
    assert r.fill_price > 100.0, "un achat taker doit remplir AU-DESSUS du mid"
    cout_implicite_bps = (r.fill_price - 100.0) / 100.0 * 10_000.0
    assert cout_implicite_bps == pytest.approx(r.net_cost_bps, rel=1e-6), (
        "le coût annoncé et le coût réellement payé dans le prix doivent coïncider"
    )


def test_a_sell_fills_below_the_mid():
    r = simulate_execution(side="SELL", notional_usdc=500.0, mid_price=100.0,
                           top_depth_usdc=1_000_000.0)
    assert r.fill_price < 100.0
    cout_implicite_bps = (100.0 - r.fill_price) / 100.0 * 10_000.0
    assert cout_implicite_bps == pytest.approx(r.net_cost_bps, rel=1e-6)


# ---------------------------------------------------------- l'audit ne double PLUS le coût

def _ledger(entry_price: float, exit_price: float, fee_in: float, fee_out: float) -> list[dict]:
    pk = "0xw|BTC|LONG"
    return [
        {"paper_action_type": "OPEN", "delta_key": "d1", "wallet_address": "0xw",
         "coin": "BTC", "leader_side": "LONG", "entry_price": entry_price,
         "copied_notional_usdt": 500.0, "fee_cost_usdc": fee_in,
         "fee_already_embedded_in_entry_price": True, "observed_at_ms": 1_000},
        {"paper_action_type": "CLOSE", "matched_position_key": pk, "coin": "BTC",
         "leader_side": "LONG", "average_entry_price": entry_price, "exit_price": exit_price,
         "notional_closed_usdt": 500.0, "fee_cost_usdc": fee_out,
         "estimated_net_pnl_usdc": 0.0, "observed_at_ms": 2_000},
    ]


def test_the_entry_fee_is_not_subtracted_a_second_time():
    """LE CŒUR. Entrée 100,05 (coût déjà dedans), sortie 101, frais de sortie 0,30 $.

    Le brut vaut déjà (101 − 100,05) × taille : le coût d'entrée l'a rongé.
    Le net ne doit retrancher QUE la sortie.
    """
    trades, _, _ = build_round_trips(_ledger(100.05, 101.0, fee_in=0.25, fee_out=0.30))
    assert len(trades) == 1
    t = trades[0]
    taille = 500.0 / 101.0
    brut_attendu = taille * (101.0 - 100.05)
    assert t["gross_pnl_recalc"] == pytest.approx(brut_attendu, abs=1e-4)
    assert t["net_pnl_recalc"] == pytest.approx(brut_attendu - 0.30, abs=1e-4), (
        "le coût d'entrée est compté DEUX FOIS : une fois dans le prix, une fois en frais"
    )


def test_a_losing_trade_is_not_made_worse_than_it_is():
    """Symétrie de l'honnêteté : on ne noircit pas non plus une perte."""
    trades, _, _ = build_round_trips(_ledger(100.05, 99.0, fee_in=0.25, fee_out=0.30))
    t = trades[0]
    taille = 500.0 / 99.0
    brut = taille * (99.0 - 100.05)
    assert t["net_pnl_recalc"] == pytest.approx(brut - 0.30, abs=1e-4)
    assert t["net_pnl_recalc"] > brut - 0.30 - 0.25, "la perte a été exagérée de 0,25 $"


# ---------------------------------------------------------- une position ouverte n'est PAS un bug

def test_an_open_position_is_not_reported_as_an_anomaly():
    """Le serveur TOURNE : une entrée sans sortie est une position ouverte, pas une orpheline.

    Crier à l'anomalie sur un état normal noie les VRAIES anomalies — et fait douter d'un
    ledger qui va bien.
    """
    events = [{"paper_action_type": "OPEN", "delta_key": "d1", "wallet_address": "0xw",
               "coin": "ETH", "leader_side": "SHORT", "entry_price": 3000.0,
               "copied_notional_usdt": 500.0, "observed_at_ms": 1_000}]
    trades, anomalies, ouvertes = build_round_trips(events)
    assert trades == []
    assert anomalies == [], "une position ouverte a été signalée comme une anomalie"
    assert len(ouvertes) == 1
    assert ouvertes[0]["coin"] == "ETH"


def test_a_real_orphan_close_is_still_an_anomaly():
    """En revanche, une SORTIE sans entrée reste une vraie anomalie — on ne relâche rien."""
    events = [{"paper_action_type": "CLOSE", "matched_position_key": "0xz|SOL|LONG",
               "coin": "SOL", "exit_price": 10.0, "observed_at_ms": 2_000}]
    _, anomalies, _ = build_round_trips(events)
    assert [a["type"] for a in anomalies] == ["FERMETURE_ORPHELINE"]


def test_a_duplicated_entry_is_still_an_anomaly():
    e = {"paper_action_type": "OPEN", "delta_key": "SAME", "wallet_address": "0xw",
         "coin": "BTC", "leader_side": "LONG", "entry_price": 100.0,
         "copied_notional_usdt": 500.0, "observed_at_ms": 1_000}
    _, anomalies, _ = build_round_trips([dict(e), dict(e)])
    assert [a["type"] for a in anomalies] == ["ENTREE_DUPLIQUEE"]
