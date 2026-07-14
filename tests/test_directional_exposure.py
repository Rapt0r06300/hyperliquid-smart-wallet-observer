"""Garde-fou d'exposition DIRECTIONNELLE (2026-07-11).

Constat en LIVE : 9 positions ouvertes, presque toutes SHORT, ~4 500 $ de notionnel sur 1 000 $ de
capital -> **250 % du capital dans un seul sens**. Le gate de portefeuille existant ne voyait rien :
il additionne des `abs()`, donc 6 shorts et 1 long lui paraissent "diversifies".

Sur le run precedent, **97 % de la perte venait des shorts** (-62,63 $ contre -1,36 $ pour les
longs), parce que le book etait short a 73 % dans un marche haussier.

Ces tests verrouillent les deux limites qui manquaient : le pari NET, et la concentration par coin.

Simulation paper uniquement. Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.risk.directional_exposure import (
    directional_refusal,
    snapshot_exposure,
)

CAPITAL = 1000.0


def _pos(coin: str, side: str, notional: float, price: float = 100.0) -> dict:
    size = notional / price
    return {
        "coin": coin,
        "direction": side,
        "side": side,
        "size": size if side == "LONG" else -size,
        "avg_price": price,
    }


def _book(*positions: dict) -> dict:
    return {f"0xw|{p['coin']}|{p['side']}|{i}": p for i, p in enumerate(positions)}


# ---------------------------------------------------------------- la photographie est juste

def test_snapshot_distinguishes_gross_from_net():
    """LE COEUR DU BUG : 6 shorts + 1 long ne sont PAS un portefeuille equilibre."""
    book = _book(*[_pos(c, "SHORT", 500) for c in ("BTC", "ETH", "SOL", "HYPE", "PUMP", "STBL")],
                 _pos("BCH", "LONG", 500))
    s = snapshot_exposure(book)
    assert s.gross_usdt == pytest.approx(3500.0)      # ce que voyait l'ancien gate
    assert s.net_usdt == pytest.approx(-2500.0)       # ce qu'il ne voyait PAS
    assert s.net_bias == "SHORT"
    assert s.short_usdt == pytest.approx(3000.0)
    assert s.long_usdt == pytest.approx(500.0)


def test_snapshot_of_a_truly_balanced_book_is_neutral():
    book = _book(_pos("BTC", "LONG", 500), _pos("ETH", "SHORT", 500))
    s = snapshot_exposure(book)
    assert s.gross_usdt == pytest.approx(1000.0)
    assert s.net_usdt == pytest.approx(0.0)
    assert s.net_bias == "NEUTRAL"


def test_snapshot_survives_garbage():
    assert snapshot_exposure({}).gross_usdt == 0.0
    assert snapshot_exposure({"a": None, "b": "x", "c": {}}).net_usdt == 0.0
    # taille ou prix nuls : la position ne compte pas (on n'invente pas un notionnel)
    assert snapshot_exposure({"a": {"coin": "X", "side": "LONG", "size": 0, "avg_price": 100}}).gross_usdt == 0.0


# ---------------------------------------------------------------- le pari NET est plafonne

def test_the_real_live_situation_is_now_refused(monkeypatch):
    """Reproduction EXACTE de la session observee : la 7e position short doit etre REFUSEE."""
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")   # net <= 1x le capital
    book = _book(*[_pos(c, "SHORT", 500) for c in ("BTC", "ETH", "SOL", "HYPE")])  # net = -2000
    refus = directional_refusal(book, coin="PUMP", side="SHORT",
                                new_notional_usdt=500, equity_usdt=CAPITAL)
    assert refus == "NET_DIRECTIONAL_EXPOSURE_TOO_HIGH", (
        "le bot continue d'empiler des shorts au-dela de 100 % du capital en pari net"
    )


def test_a_trade_that_rebalances_is_always_allowed(monkeypatch):
    """On ne bloque JAMAIS le trade qui rapproche le portefeuille de la neutralite."""
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    book = _book(*[_pos(c, "SHORT", 500) for c in ("BTC", "ETH", "SOL", "HYPE", "PUMP")])  # net -2500
    # un LONG reduit le desequilibre -> accepte, meme si le net reste au-dessus du plafond
    assert directional_refusal(book, coin="BCH", side="LONG",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == ""


def test_a_moderate_net_bias_is_allowed(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    book = _book(_pos("BTC", "SHORT", 500))            # net = -500 (50 % du capital)
    assert directional_refusal(book, coin="ETH", side="SHORT",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == ""   # -1000 = 100 %


def test_the_cap_is_relative_to_capital(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    book = _book(_pos("BTC", "SHORT", 500), _pos("ETH", "SHORT", 500))   # net = -1000
    assert directional_refusal(book, coin="SOL", side="SHORT",
                               new_notional_usdt=500, equity_usdt=1000.0) != ""     # 150 % -> refuse
    assert directional_refusal(book, coin="SOL", side="SHORT",
                               new_notional_usdt=500, equity_usdt=5000.0) == ""     # 30 % -> accepte


# ---------------------------------------------------------------- la concentration par coin

def test_two_positions_on_the_same_market_are_capped(monkeypatch):
    """Deux positions ETH SHORT simultanees ont ete observees en live."""
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "1000")   # on isole le test coin
    monkeypatch.setenv("HYPERSMART_MAX_COIN_NOTIONAL_PCT", "60")       # <= 600 $ sur un marche
    book = _book(_pos("ETH", "SHORT", 500))
    assert directional_refusal(book, coin="ETH", side="SHORT",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == "COIN_CONCENTRATION_TOO_HIGH"
    # un AUTRE marche reste possible
    assert directional_refusal(book, coin="SOL", side="SHORT",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == ""


def test_concentration_counts_both_sides_of_a_market(monkeypatch):
    """Long ET short sur le meme coin, c'est toujours du risque sur ce marche."""
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "1000")
    monkeypatch.setenv("HYPERSMART_MAX_COIN_NOTIONAL_PCT", "60")
    book = _book(_pos("ETH", "LONG", 500))
    assert directional_refusal(book, coin="ETH", side="SHORT",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == "COIN_CONCENTRATION_TOO_HIGH"


# ---------------------------------------------------------------- robustesse du garde-fou

def test_an_invalid_cap_falls_back_to_the_default_not_to_infinity(monkeypatch):
    """DENY-BY-DEFAULT : un plafond a 0 ou negatif est INVALIDE, pas 'illimite'."""
    book = _book(*[_pos(c, "SHORT", 500) for c in ("BTC", "ETH", "SOL", "HYPE")])
    for mauvais in ("0", "-5", "", "abc"):
        monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", mauvais)
        assert directional_refusal(book, coin="PUMP", side="SHORT",
                                   new_notional_usdt=500, equity_usdt=CAPITAL) != "", (
            f"un plafond invalide ({mauvais!r}) desactive le garde-fou -> fail-open"
        )


def test_the_guard_never_crashes_the_loop():
    """Un garde-fou de risque ne doit jamais faire tomber la boucle de trading."""
    for book in ({}, None, {"x": None}, {"y": {"coin": "Z"}}):
        assert directional_refusal(book or {}, coin="BTC", side="SHORT",
                                   new_notional_usdt=500, equity_usdt=CAPITAL) in {
            "", "NET_DIRECTIONAL_EXPOSURE_TOO_HIGH", "COIN_CONCENTRATION_TOO_HIGH"}
    # entrees degenerees : on ne juge pas, les autres gates s'en chargent
    assert directional_refusal({}, coin="BTC", side="SHORT", new_notional_usdt=0, equity_usdt=1000) == ""
    assert directional_refusal({}, coin="BTC", side="SHORT", new_notional_usdt=500, equity_usdt=0) == ""
    assert directional_refusal({}, coin="BTC", side="???", new_notional_usdt=500, equity_usdt=1000) == ""


def test_an_empty_book_accepts_a_first_position(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    assert directional_refusal({}, coin="BTC", side="SHORT",
                               new_notional_usdt=500, equity_usdt=CAPITAL) == ""


# ======================================================================================
#  VERROU : le refus du PaperEngine ne doit JAMAIS etre contourne
#
#  Un audit externe a soupconne un bypass en observant `paper_engine_accepted=0` alors que
#  6 positions etaient ouvertes. Verification faite : il n'y a PAS de bypass -- le compteur
#  affiche celui du TICK COURANT, tandis que les positions viennent de ticks anterieurs ou
#  le moteur avait accepte. Ce test verrouille le comportement pour qu'il le reste.
# ======================================================================================

def _heartbeat(accepted: bool) -> dict:
    return {
        "status": "OK_LIVE_FUSION_RUNTIME",
        "paper_only": True,
        "real_execution": False,
        "paper_engine": {
            "accepted_count": 1 if accepted else 0,
            "decisions": [{
                "accepted": accepted,
                "reason_codes": [] if accepted else ["EDGE_REMAINING_BELOW_MINIMUM"],
                "trade": {"trade_id": "t1", "coin": "BTC", "side": "SHORT",
                          "fill_price": 60000.0, "notional_usdt": 500.0, "fees_and_cost_bps": 6.0},
                "position": {"coin": "BTC", "side": "SHORT", "entry_price": 60000.0,
                             "quantity": 0.00833, "notional_usdt": 500.0,
                             "leader_wallet": "0xw", "source_delta_id": "d1"},
            }],
        },
        "runtime": {"session": {"session_id": "s1"}, "paper_orders": []},
    }


def test_a_refused_trade_never_becomes_a_position():
    """Si le PaperEngine refuse (edge sous le minimum), AUCUNE position ne doit naitre."""
    from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
    from hl_observer.ui.state import UiState

    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    report = apply_fusion_paper_orders_to_state(state, _heartbeat(False), current_ms=1_000_000)
    assert report["applied_count"] == 0
    assert not state.simulation_virtual_positions, (
        "CONTOURNEMENT DU MOTEUR : une position est nee malgre le refus du PaperEngine"
    )


def test_an_accepted_trade_does_become_a_position():
    """Symetrie : sans cela, le test precedent passerait meme si le chemin etait mort."""
    from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
    from hl_observer.ui.state import UiState

    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    report = apply_fusion_paper_orders_to_state(state, _heartbeat(True), current_ms=1_000_000)
    assert report["applied_count"] == 1
    assert len(state.simulation_virtual_positions) == 1


def test_the_directional_guard_is_wired_into_the_portfolio_gate(monkeypatch):
    """Le garde-fou doit etre CABLE, pas seulement exister : 5 shorts puis un 6e -> refus."""
    from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
    from hl_observer.ui.state import UiState

    monkeypatch.setenv("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", "100")
    # ---------------------------------------------------------------------------------
    # 2026-07-12 -- CE TEST NE TESTAIT PAS CE QU'IL CROYAIT.
    #
    # Il echouait avec `PORTFOLIO_MAX_OPEN_POSITIONS` : le plafond du NOMBRE de positions
    # tirait AVANT le garde-fou directionnel, qui n'avait donc jamais la parole. Le 6e short
    # etait bien refuse -- mais pour une raison qui n'a rien a voir avec le pari net.
    #
    # Pire : ce plafond depend de l'ENVIRONNEMENT (`HYPERSMART_MAX_OPEN_POSITIONS`). Le test
    # changeait donc de verdict selon la machine. Un test qui depend de l'env ne prouve rien.
    #
    # On desserre explicitement le plafond de COMPTE pour isoler la variable qu'on mesure :
    # le garde-fou d'exposition NETTE. C'est la seule facon de savoir s'il est vraiment cable.
    # ---------------------------------------------------------------------------------
    monkeypatch.setenv("HYPERSMART_MAX_OPEN_POSITIONS", "50")
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    # le book est deja short a 250 % du capital
    state.simulation_virtual_positions = _book(
        *[_pos(c, "SHORT", 500) for c in ("ETH", "SOL", "HYPE", "PUMP", "STBL")]
    )
    report = apply_fusion_paper_orders_to_state(state, _heartbeat(True), current_ms=1_000_000)
    assert report["applied_count"] == 0, "un 6e short a ete accepte malgre 250 % de pari net"
    assert any("NET_DIRECTIONAL" in str(r) for r in report["reasons"]), (
        f"le garde-fou directionnel n'est pas cable dans le gate portefeuille : {report['reasons']}"
    )
