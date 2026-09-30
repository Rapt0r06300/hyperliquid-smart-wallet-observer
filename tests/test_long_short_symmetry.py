"""LONG et SHORT doivent être traités À L'IDENTIQUE (2026-07-11) — piste P6c.

LE CONSTAT QUI A DÉCLENCHÉ CETTE ENQUÊTE : **19 ouvertures sur 21 étaient SHORT**, et
**les 16 positions clôturées étaient TOUTES SHORT**. Sur le run précédent, **97 % de la perte
venait des shorts**. Une concentration pareille appelle une question simple : le code
favorise-t-il un sens ?

**RÉPONSE MESURÉE : NON.** L'edge, le PnL, le SL/TP, le coût d'exécution : tout est symétrique.
Le biais vient de la **SOURCE** — les leaders copiés shortaient, dans un marché qui montait.
Le bot a fidèlement reproduit un pari perdant. Ce n'est pas un bug de code, c'est un **risque de
concentration** — et c'est le garde-fou d'exposition NETTE qui doit l'arrêter (il le fait
désormais : `risk/directional_exposure.py`).

Ces tests VERROUILLENT la symétrie : si un futur changement introduit une préférence de sens —
même involontaire — ils tombent. Une asymétrie cachée transformerait chaque perte en gain
apparent, ou l'inverse. C'est le genre de bug qu'on ne voit jamais venir.

Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.exec_model import simulate_execution
from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp, signed_pnl_bps


# ------------------------------------------------------------------ le PnL

def test_a_favourable_move_pays_the_same_on_both_sides():
    """+2 % pour un LONG et −2 % pour un SHORT doivent rapporter EXACTEMENT autant."""
    assert signed_pnl_bps("LONG", 100.0, 102.0) == signed_pnl_bps("SHORT", 100.0, 98.0)


def test_an_adverse_move_costs_the_same_on_both_sides():
    assert signed_pnl_bps("LONG", 100.0, 98.0) == signed_pnl_bps("SHORT", 100.0, 102.0)


def test_the_pnl_sign_is_never_flipped():
    """LE PIÈGE ABSOLU : une inversion de signe ferait passer chaque perte pour un gain."""
    assert signed_pnl_bps("LONG", 100.0, 102.0) > 0
    assert signed_pnl_bps("LONG", 100.0, 98.0) < 0
    assert signed_pnl_bps("SHORT", 100.0, 98.0) > 0
    assert signed_pnl_bps("SHORT", 100.0, 102.0) < 0


# ------------------------------------------------------------------ les barrières

def test_the_stop_and_the_target_trigger_at_the_same_distance():
    """Un stop qui se déclenche plus tôt d'un côté créerait un biais invisible et coûteux."""
    cfg = SLTPConfig(stop_loss_bps=100.0, take_profit_bps=200.0)

    tp_long = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=102.0,
                             peak_price=102.0, config=cfg)
    tp_short = evaluate_sl_tp(side="SHORT", entry_price=100.0, current_price=98.0,
                              peak_price=98.0, config=cfg)
    assert tp_long.exit == tp_short.exit
    assert tp_long.reason == tp_short.reason

    sl_long = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=98.9,
                             peak_price=100.0, config=cfg)
    sl_short = evaluate_sl_tp(side="SHORT", entry_price=100.0, current_price=101.1,
                              peak_price=100.0, config=cfg)
    assert sl_long.exit == sl_short.exit
    assert sl_long.reason == sl_short.reason


# ------------------------------------------------------------------ le coût d'exécution

def test_buying_and_selling_cost_exactly_the_same():
    """Un coût asymétrique pousserait le bot vers un sens — et 97 % de la perte venait des shorts."""
    achat = simulate_execution(side="BUY", notional_usdc=500.0, mid_price=100.0,
                               top_depth_usdc=100_000.0)
    vente = simulate_execution(side="SELL", notional_usdc=500.0, mid_price=100.0,
                               top_depth_usdc=100_000.0)
    assert achat.net_cost_bps == pytest.approx(vente.net_cost_bps)
    # et le fill est défavorable des DEUX côtés (jamais un cadeau d'un seul)
    assert achat.fill_price > 100.0 > vente.fill_price
    assert (achat.fill_price - 100.0) == pytest.approx(100.0 - vente.fill_price)


def test_the_latency_costs_the_same_in_both_directions():
    achat = simulate_execution(side="BUY", notional_usdc=500.0, mid_price=100.0,
                               top_depth_usdc=100_000.0, latency_sec=30.0)
    vente = simulate_execution(side="SELL", notional_usdc=500.0, mid_price=100.0,
                               top_depth_usdc=100_000.0, latency_sec=30.0)
    assert achat.latency_bps == pytest.approx(vente.latency_bps)


# ------------------------------------------------------------------ l'edge de décision

def test_the_consensus_edge_does_not_favour_a_direction():
    """L'edge (proxy hérité) doit dépendre de la FORCE du consensus, jamais de son SENS."""
    import hl_observer.strategies.fusion_runtime  # noqa: F401  (ordre d'import applicatif)
    from hl_observer.paper_trading.fusion_paper_engine_adapter import (
        _consensus_edge_remaining_bps,
    )

    class _Conflit:
        def __init__(self, long_score: float, short_score: float) -> None:
            self.long_score = long_score
            self.short_score = short_score

    pour_long = _consensus_edge_remaining_bps(_Conflit(80.0, 20.0), distinct_wallets=3)
    pour_short = _consensus_edge_remaining_bps(_Conflit(20.0, 80.0), distinct_wallets=3)
    assert pour_long == pytest.approx(pour_short), (
        "l'edge dépend du SENS du consensus : le bot préfère structurellement une direction"
    )


# ------------------------------------------------------------------ le garde-fou de concentration

def test_the_net_exposure_guard_stops_a_one_sided_book(monkeypatch):
    """Le vrai remède au biais SHORT : ce n'est pas la symétrie du code (elle est acquise),
    c'est le plafond d'exposition NETTE. 9 shorts d'affilée doivent être refusés."""
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    from hl_observer.risk.directional_exposure import directional_refusal

    book = {
        f"0xw|{coin}|SHORT": {"coin": coin, "side": "SHORT", "direction": "SHORT",
                              "size": -5.0, "avg_price": 100.0}
        for coin in ("BTC", "ETH", "SOL", "HYPE")
    }
    assert directional_refusal(book, coin="PUMP", side="SHORT",
                               new_notional_usdt=500.0, equity_usdt=1000.0) != "", (
        "le bot peut encore empiler les shorts : le biais des leaders devient notre perte"
    )
