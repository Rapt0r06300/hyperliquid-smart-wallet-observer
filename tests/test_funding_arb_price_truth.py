"""LE FUNDING-ARB N'A QU'UNE JAMBE — son PnL doit compter le PRIX (2026-07-11).

LE BUG LE PLUS DANGEREUX DE TOUS, ET IL N'A JAMAIS TIRÉ.

La « paire delta-neutre » du funding-arb n'a **qu'une seule jambe** (`receiving_side`). Il n'y a
aucune couverture : juste un frais forfaitaire (`hedge_venue_extra_bps = 1 bps`) qui fait *semblant*
d'en être une. C'est donc une position **NUE** sur un perp.

Or son PnL valait :

    net = funding encaissé − coûts          ← AUCUN terme de prix

Un revenu de funding **sans risque de marché**. Ça n'existe pas. C'était du **PnL fabriqué**.

Concrètement : short CASHCAT pour encaisser 6,5 bps/h de funding pendant que le coin monte de 5 %
→ le modèle affichait un **gain**, la réalité est **−500 bps**.

**Le verrou d'entrée mort nous a accidentellement protégés.** Si j'avais baissé le seuil en voyant
« QUASI-MORT » — ce que la logique appelait — le Grinder se serait mis à imprimer des profits
fictifs. C'est exactement pour ça qu'on mesure AVANT de régler.

Simulation paper uniquement. Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.funding_arb_paper import (

    FundingArbConfig,
    FundingArbPosition,
    evaluate_funding_arb,
)

H = 3_600_000
NOW = 1_800_000_000_000

# funding mort -> la position se ferme au tick suivant (FUNDING_EDGE_COLLAPSED)
_FUNDING_MORT = [0.0] * 10


def _position(side: str, *, entry_price: float, notional: float = 25.0) -> FundingArbPosition:
    return FundingArbPosition(
        pair_id="fundingarb:TEST:1",
        coin="TEST",
        receiving_side=side,
        leg_notional_usdt=notional,
        entry_rate_bps_per_hour=3.0,
        opened_at_ms=NOW - 2 * H,
        entry_price=entry_price,
        accrued_funding_usdc=0.10,          # 10 cents de funding encaissé
        entry_costs_usdc=0.0075,
        last_accrual_at_ms=NOW - 2 * H,
    )


def _fermer(pos: FundingArbPosition, prix_sortie: float):
    rapport = evaluate_funding_arb(
        funding_rows=({"coin": "TEST", "rates": _FUNDING_MORT},),
        prices={"TEST": prix_sortie},
        positions=(pos,),
        now_ms=NOW,
        config=FundingArbConfig(min_entry_edge_bps_per_hour=999.0),   # aucune nouvelle entrée
    )
    closes = [e for e in rapport.events if e.action == "CLOSE"]
    assert closes, "la position aurait dû se fermer (funding mort)"
    return closes[0], rapport


# ------------------------------------------------------- LE scénario qui fabriquait du profit

def test_a_short_that_gets_run_over_by_the_price_now_LOSES_money():
    """LE TEST QUI COMPTE. Short pour encaisser du funding, le coin monte de 5 %.

    Avant : le modèle affichait un GAIN (funding encaissé, prix ignoré).
    Maintenant : la perte de prix domine, et le PnL le DIT.
    """
    pos = _position("SHORT", entry_price=100.0)
    close, rapport = _fermer(pos, prix_sortie=105.0)          # +5 % contre nous

    assert close.price_pnl_usdc == pytest.approx(-1.25)       # 25 $ × −5 %
    assert close.net_pnl_usdc < 0, (
        "le PnL est POSITIF alors que le short s'est fait écraser : le prix est encore ignoré"
    )
    assert rapport.realized_pnl_usdc < 0


def test_a_long_that_gets_run_over_also_loses():
    """Symétrie : un LONG qui encaisse du funding pendant que le coin s'effondre doit perdre."""
    pos = _position("LONG", entry_price=100.0)
    close, _ = _fermer(pos, prix_sortie=95.0)
    assert close.price_pnl_usdc == pytest.approx(-1.25)
    assert close.net_pnl_usdc < 0


def test_a_favourable_price_move_is_credited_too():
    """Honnêteté dans l'autre sens : si le prix va dans notre sens, on l'encaisse."""
    pos = _position("SHORT", entry_price=100.0)
    close, _ = _fermer(pos, prix_sortie=98.0)                 # −2 % : favorable à un short
    assert close.price_pnl_usdc == pytest.approx(0.50)        # 25 $ × 2 %
    assert close.net_pnl_usdc > 0


def test_the_funding_alone_can_no_longer_carry_the_pnl():
    """Le funding seul ne suffit plus à faire un PnL positif si le prix a bougé contre nous.

    C'est TOUT le point : 10 cents de funding ne compensent pas 1,25 $ de perte de prix.
    """
    pos = _position("SHORT", entry_price=100.0)
    close, _ = _fermer(pos, prix_sortie=105.0)
    assert pos.accrued_funding_usdc == 0.10
    assert abs(close.price_pnl_usdc) > pos.accrued_funding_usdc * 10


# ------------------------------------------------------- la vérité des données

def test_an_unknown_price_is_flagged_not_invented():
    """RÈGLE DURE : pas de prix → on NE SAIT PAS ce qu'a fait la position. On ne l'invente pas."""
    pos = _position("SHORT", entry_price=100.0)
    close, report = _fermer(pos, prix_sortie=0.0)             # prix indisponible
    assert close.price_pnl_usdc is None
    assert close.price_pnl_unknown is True
    assert close.net_pnl_usdc is None
    assert report.realized_pnl_usdc == 0.0
    assert "PNL_UNMEASURABLE" in close.reason


def test_a_legacy_position_without_entry_price_is_flagged():
    """Une position ouverte AVANT ce correctif n'a pas de prix d'entrée : on ne devine pas."""
    pos = _position("SHORT", entry_price=0.0)                 # legacy
    close, _ = _fermer(pos, prix_sortie=105.0)
    assert close.price_pnl_usdc is None
    assert close.price_pnl_unknown is True


def test_funding_unknown_price_pnl_never_enters_strict_realized():
    pos = _position("SHORT", entry_price=100.0)
    close, report = _fermer(pos, prix_sortie=0.0)

    assert close.net_pnl_usdc is None
    assert report.realized_pnl_usdc == 0.0


def test_funding_event_identity_is_stable_across_replays():
    pos = _position("SHORT", entry_price=100.0)

    first, _ = _fermer(pos, prix_sortie=98.0)
    second, _ = _fermer(pos, prix_sortie=98.0)

    assert first.event_id == second.event_id
    assert first.event_id == f"{pos.pair_id}:close"


def test_a_new_position_records_its_entry_price():
    """Sans prix d'entrée mémorisé, aucun PnL de prix ne sera jamais calculable."""
    rapport = evaluate_funding_arb(
        funding_rows=({"coin": "TEST", "rates": [0.0005] * 10},),   # 5 bps/h : franchit le seuil
        prices={"TEST": 42.0},
        positions=(),
        now_ms=NOW,
        config=FundingArbConfig(min_entry_edge_bps_per_hour=2.5, spike_sigma=99.0),
    )
    assert rapport.positions, "aucune position ouverte : le test ne prouve rien"
    assert rapport.positions[0].entry_price == 42.0


# ------------------------------------------------------- le sens ne doit pas s'inverser

def test_the_side_sign_is_not_flipped():
    """Une erreur de signe ici transformerait chaque perte en gain. C'est LE piège."""
    haut = _fermer(_position("SHORT", entry_price=100.0), 110.0)[0]
    bas = _fermer(_position("SHORT", entry_price=100.0), 90.0)[0]
    assert haut.price_pnl_usdc < 0 < bas.price_pnl_usdc, "le signe du SHORT est inversé"

    haut_l = _fermer(_position("LONG", entry_price=100.0), 110.0)[0]
    bas_l = _fermer(_position("LONG", entry_price=100.0), 90.0)[0]
    assert bas_l.price_pnl_usdc < 0 < haut_l.price_pnl_usdc, "le signe du LONG est inversé"


# ---------------------------------------------------------------------------------------------
# VERROU CARRY (2026-07-11) -- POURQUOI CES TESTS FORCENT UN FLAG.
#
# Ces tests verifient la MECANIQUE du moteur funding (accrual, caps, sortie, PnL). Pour cela, il
# faut qu'une position s'ouvre. Or depuis la mesure du 2026-07-11, le moteur REFUSE par defaut
# d'ouvrir une jambe NUE :
#
#     232 marches, 9 512 releves : funding median 0,125 bps/h contre ~35 bps/h de mouvement de
#     prix. Pour 1 bps de funding encaisse, une jambe nue subit ~281 bps de mouvement de prix.
#
# On active donc explicitement `HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG=1` : c'est un mode A/B
# ASSUME, PAS le comportement de production. Le defaut, lui, reste le REFUS -- et c'est
# `tests/test_funding_carry_economics.py` qui garde cette regle.
# ---------------------------------------------------------------------------------------------
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _autoriser_jambe_nue_pour_tester_la_mecanique(monkeypatch):
    """Mode A/B : on ouvre la vanne pour pouvoir tester l'interieur du moteur."""
    monkeypatch.setenv("HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG", "1")
