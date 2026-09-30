"""LE FLUX PAYE-T-IL LE RISQUE ? (2026-07-12) — trades publics + selection adverse.

CE QUE LE CARNET NE POUVAIT PAS DIRE.

Le carnet L2 a donne 10 candidats (spread > frais, profondeur OK, toxicite acceptable). Mais un
carnet ne dit pas s'il y a QUELQU'UN EN FACE. Un market maker gagne = spread x volume echange
CONTRE LUI. Un spread de 49 bps que personne ne traverse rapporte ZERO -- on porte juste
l'inventaire d'un coin illiquide.

Et surtout, le carnet ne dit rien de la SELECTION ADVERSE : on est rempli PRECISEMENT quand on a
tort. Quelqu'un achete a mon ask parce qu'il pense que ca monte ; souvent ca monte ; je suis
maintenant SHORT sur un marche qui monte. Les quelques bps de spread ne paient pas les dizaines
de bps que je viens de subir.

C'est ca qui tue les market makers -- pas les frais.

Aucun ordre reel. Canal public, lecture seule.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.market_making_flow import (
    COUT_ALLER_RETOUR_BPS,
    FENETRE_MIN_OBSERVATION_S,
    MIN_TRADES,
    MIN_TRADES_POUR_CONCLURE,
    evaluer_market_making,
    selection_adverse_bps,
)
from hl_observer.collection.trades_recorder import (
    ENV_ACTIF,
    Trade,
    actif,
    message_abonnement,
    parse_trade,
)

T0 = 1_800_000.0


def _flux(n=60, *, agresseur="BUY", derive_bps=0.0, prix0=100.0, pas_s=6.0):
    """Un flux de trades. `derive_bps` = mouvement du prix par trade, dans le sens de l'agresseur."""
    out = []
    px = prix0
    for i in range(n):
        out.append({
            "coin": "TEST", "ts": T0 + i * pas_s, "px": px, "sz": 5.0,
            "aggressor": agresseur, "notional_usd": px * 5.0,
        })
        sens = 1.0 if agresseur == "BUY" else -1.0
        px *= 1.0 + sens * derive_bps / 10_000.0
    return out


# ============================================================ LE PARSING (canal public `trades`)

def test_a_public_trade_is_parsed_with_its_AGGRESSOR_side():
    """L'agresseur est TOUT : c'est lui qui dit de quel cote le maker a ete rempli."""
    trades = parse_trade({"channel": "trades", "data": [
        {"coin": "HMSTR", "side": "B", "px": "0.0031", "sz": "1000", "time": 1_800_000_000},
    ]})
    assert len(trades) == 1
    t = trades[0]
    assert t.coin == "HMSTR" and t.agresseur == "BUY"
    assert t.notionnel_usd == pytest.approx(3.1)


def test_side_A_means_the_aggressor_SOLD_into_the_bid():
    t = parse_trade({"channel": "trades", "data": [
        {"coin": "ACE", "side": "A", "px": "2.0", "sz": "10", "time": 1},
    ]})[0]
    assert t.agresseur == "SELL"


def test_a_trade_with_an_UNKNOWN_side_is_DROPPED_not_guessed():
    """Sans le cote agresseur, le trade est inutilisable pour un market maker. On ne devine PAS."""
    assert parse_trade({"channel": "trades", "data": [
        {"coin": "X", "side": "?", "px": "1", "sz": "1", "time": 1},
    ]}) == []


def test_incomplete_trades_are_dropped():
    assert parse_trade({"channel": "trades", "data": [
        {"coin": "X", "side": "B", "px": "0", "sz": "1", "time": 1},          # prix nul
        {"coin": "X", "side": "B", "px": "1", "sz": "0", "time": 1},          # taille nulle
        {"coin": "", "side": "B", "px": "1", "sz": "1", "time": 1},           # sans coin
        {"coin": "X", "side": "B", "px": "abc", "sz": "1", "time": 1},        # prix illisible
    ]}) == []


def test_another_channel_is_ignored():
    assert parse_trade({"channel": "l2Book", "data": [{"coin": "X"}]}) == []
    assert parse_trade({}) == []


def test_the_subscription_is_the_PUBLIC_trades_channel_only():
    """AUCUN message d'ordre ne sort JAMAIS. Les seuls messages sortants sont des `subscribe`."""
    msgs = message_abonnement(["hmstr", "ACE", ""])
    assert len(msgs) == 2
    for m in msgs:
        assert m["method"] == "subscribe"
        assert m["subscription"]["type"] == "trades"
        assert "signature" not in str(m) and "order" not in str(m).lower()


def test_recording_is_OFF_by_default(monkeypatch):
    monkeypatch.delenv(ENV_ACTIF, raising=False)
    assert actif() is False


# ============================================================ LA SELECTION ADVERSE

def test_a_price_that_FOLLOWS_the_aggressor_means_the_maker_LOST():
    """LE TEST QUI COMPTE. Des acheteurs agressifs, et le prix monte apres.
    Le maker etait a l'ask -> il est SHORT -> il perd. La perte doit etre POSITIVE."""
    adverse, n = selection_adverse_bps(_flux(120, agresseur="BUY", derive_bps=2.0))
    assert n >= MIN_TRADES
    assert adverse is not None and adverse > 0, "une derive dans le sens de l'agresseur = une perte"


def test_a_price_that_goes_AGAINST_the_aggressor_means_the_maker_WON():
    """Le cas heureux : l'agresseur achete, et le prix redescend. Le maker encaisse."""
    adverse, _ = selection_adverse_bps(_flux(120, agresseur="BUY", derive_bps=-2.0))
    assert adverse is not None and adverse < 0


def test_a_flat_price_means_NO_adverse_selection():
    adverse, _ = selection_adverse_bps(_flux(120, derive_bps=0.0))
    assert adverse == pytest.approx(0.0, abs=0.01)


def test_the_sign_is_INVERTED_for_a_selling_aggressor():
    """Un vendeur agressif remplit un maker au BID -> le maker est LONG -> il perd si ca BAISSE."""
    adverse, _ = selection_adverse_bps(_flux(120, agresseur="SELL", derive_bps=2.0))
    assert adverse is not None and adverse > 0


def test_too_few_trades_NEVER_produce_a_number():
    """Deny-by-default : sans echantillon, on ne conclut pas. Jamais."""
    adverse, _ = selection_adverse_bps(_flux(5))
    assert adverse is None


# ============================================================ LE VERDICT

def test_adverse_selection_can_KILL_a_market_with_a_beautiful_spread():
    """LE PIEGE. Spread de 50 bps, profondeur OK, du flux... et perdant quand meme.
    Parce que le prix suit l'agresseur : on est rempli exactement quand on a tort."""
    # spread 50 bps -> on capture 25. Frais : 3. Il "reste" 22 bps.
    # Mais le prix suit l'agresseur de 6 bps par trade -> sur l'horizon de 30 s (5 trades),
    # on subit ~30 bps. On est rempli EXACTEMENT quand on a tort. Le spread ne paie pas.
    v = evaluer_market_making("PIEGE", _flux(400, agresseur="BUY", derive_bps=6.0),
                              spread_bps=50.0)
    assert v.selection_adverse_bps is not None and v.selection_adverse_bps > 22, (
        "la selection adverse doit depasser ce qui reste apres capture et frais"
    )
    assert v.pnl_net_bps is not None and v.pnl_net_bps < 0
    assert "PERDANT" in v.verdict


def test_a_market_with_flow_and_NO_adverse_selection_is_a_real_candidate():
    """Le seul cas qui vaut : du flux, un vrai spread, et le prix qui ne te punit pas."""
    v = evaluer_market_making("BON", _flux(400, derive_bps=0.0, pas_s=6.0), spread_bps=40.0)
    assert v.pnl_net_bps is not None and v.pnl_net_bps > 0
    assert v.pnl_par_h_usd is not None and v.pnl_par_h_usd > 0
    assert "CANDIDAT" in v.verdict


def test_a_wide_spread_with_NO_FLOW_earns_NOTHING():
    """Le coeur du sujet : 49 bps de spread que personne ne traverse = zero revenu."""
    v = evaluer_market_making("DESERT", _flux(10), spread_bps=49.0)
    assert v.pnl_par_h_usd is None, "49 bps de spread que personne ne traverse = ZERO"


def test_the_fees_are_counted_and_never_a_rebate():
    """Chez Hyperliquid le maker PAIE. Un spread inferieur aux frais ne peut pas gagner."""
    assert COUT_ALLER_RETOUR_BPS == 3.0
    v = evaluer_market_making("MAJOR", _flux(400, derive_bps=0.0), spread_bps=0.2)
    assert v.pnl_net_bps is not None and v.pnl_net_bps < 0


def test_the_model_ALWAYS_states_its_hypothesis():
    """Un modele qui cache son hypothese est un mensonge avec des decimales."""
    v = evaluer_market_making("X", _flux(400), spread_bps=20.0)
    assert "% du spread" in v.hypothese and "% du flux" in v.hypothese
    assert "sans colocation" in v.hypothese


def test_the_verdict_never_claims_a_real_execution():
    v = evaluer_market_making("X", _flux(400), spread_bps=20.0)
    assert v.as_dict()["real_execution"] is False


# =============================================================================================
# LE BUG QUE J'AI ECRIT MOI-MEME (2026-07-12) — et qui a failli fabriquer un espoir
# =============================================================================================
#
# Mon modele calculait les fills sur le NOMBRE de trades :
#     fills_h = trades_par_min x 60 x part_du_flux    puis    x 500 $
#
# Sur ACE (23,70 $ de volume par MINUTE), il annonçait 6,6 fills de 500 $ = 3 300 $/h...
# sur un marche qui echange 1 422 $/h AU TOTAL.
#
# LE MODELE REMPLISSAIT DEUX FOIS LE VOLUME DU MARCHE ENTIER.
#
# Resultat affiche : 137 $/jour. Resultat reel : 5,91 $/jour. Surestimation x23.
#
# ON NE PEUT PAS ETRE REMPLI DE PLUS DE DOLLARS QU'IL N'EN TRAVERSE LE SPREAD.
# Le volume est le plafond. Toujours.


def _flux_realiste(n, *, vol_par_trade, pas_s=6.0, derive_bps=0.0):
    """Un flux avec des tailles de trade REELLES -- pas des unites abstraites."""
    out = []
    px = 100.0
    for i in range(n):
        out.append({
            "coin": "T", "ts": T0 + i * pas_s, "px": px,
            "sz": vol_par_trade / px, "aggressor": "BUY",
            "notional_usd": vol_par_trade,
        })
        px *= 1.0 + derive_bps / 10_000.0
    return out


def test_the_model_can_NEVER_fill_more_dollars_than_the_market_TRADES():
    """LE TEST QUI M'AURAIT SAUVE. Un marche minuscule ne peut pas nous remplir gros."""
    # 400 trades de 20 $ sur 400 s -> 20 $/s = 1 200 $/min de volume
    trades = _flux_realiste(400, vol_par_trade=20.0, pas_s=6.0)
    v = evaluer_market_making("MINUSCULE", trades, spread_bps=40.0, taille_usd=500.0,
                              part_du_flux=0.10)

    volume_total_h = v.volume_par_min_usd * 60.0
    if v.pnl_par_h_usd is not None:
        # notre PnL ne peut pas depasser 100 % du volume traverse (et de tres loin)
        assert abs(v.pnl_par_h_usd) < volume_total_h, (
            "le modele gagne %.2f $/h sur un marche qui n'echange que %.2f $/h"
            % (v.pnl_par_h_usd, volume_total_h)
        )
    # et les fills equivalents doivent tenir dans notre part du volume
    assert v.fills_par_h_estimes * 500.0 <= volume_total_h * 0.10 + 1e-6


def test_a_market_with_TINY_trades_gives_a_TINY_pnl():
    """ACE : 23,70 $/min de volume. Meme avec un edge parfait, on ne peut pas gagner gros."""
    trades = _flux_realiste(400, vol_par_trade=21.0, pas_s=55.0)   # ~23 $/min
    v = evaluer_market_making("ACE_REEL", trades, spread_bps=13.5, taille_usd=500.0)
    if v.pnl_par_h_usd is not None:
        assert v.pnl_par_h_usd < 1.0, (
            "23 $/min de volume ne peuvent PAS produire plus de quelques centimes par heure"
        )


def test_31_trades_are_NEVER_enough_to_declare_a_candidate():
    """31 trades, c'est un pile ou face. Pas une mesure. Le verdict doit le DIRE."""
    trades = _flux_realiste(31, vol_par_trade=100.0)
    v = evaluer_market_making("PETIT", trades, spread_bps=50.0)
    assert v.pnl_par_h_usd is None, "aucun chiffre en dollars sur 31 trades"


def test_a_LARGE_sample_is_required_before_ANY_dollar_figure_is_shown():
    """Aucun chiffre en dollars ne sort tant que l'echantillon ne le merite pas."""
    assert MIN_TRADES_POUR_CONCLURE >= 300
    petit = evaluer_market_making("X", _flux_realiste(299, vol_par_trade=100.0), spread_bps=50.0)
    assert petit.pnl_par_h_usd is None


# =============================================================================================
# LE SNAPSHOT N'EST PAS DU FLUX — et une RAFALE n'est pas un DEBIT (2026-07-12)
# =============================================================================================
#
# DEUX PIEGES QUE J'AI ECRITS MOI-MEME :
#
# 1. A la souscription, Hyperliquid renvoie les DERNIERS trades. C'est de l'HISTORIQUE.
#    Presque tous les marches montraient exactement 30 trades : c'etait le snapshot.
#    Le compter comme du temps reel fabrique un volume qui n'existe pas.
#
# 2. CASHCAT : 86 trades en 14 SECONDES -> extrapoles a 9,5 M$/h. Une rafale n'est pas un debit.


def test_the_initial_SNAPSHOT_is_never_counted_as_live_flow():
    """Le snapshot est de l'HISTORIQUE. Le compter comme du flux fabrique du volume."""
    snap = [{**t, "snapshot": True} for t in _flux_realiste(400, vol_par_trade=100.0)]
    v = evaluer_market_making("SNAP", snap, spread_bps=50.0)
    assert v.pnl_par_h_usd is None
    assert "SNAPSHOT" in v.verdict or "FLUX QUASI NUL" in v.verdict


def test_snapshot_and_live_trades_are_SEPARATED():
    """Un marche avec un gros snapshot mais AUCUN flux vivant doit etre refuse."""
    snap = [{**t, "snapshot": True} for t in _flux_realiste(500, vol_par_trade=100.0)]
    live = _flux_realiste(5, vol_par_trade=100.0)          # 5 trades vivants seulement
    v = evaluer_market_making("MIXTE", snap + live, spread_bps=50.0)
    assert v.pnl_par_h_usd is None
    assert v.n_trades == 5, "seuls les trades VIVANTS comptent"


def test_a_14_second_BURST_is_NEVER_extrapolated_to_an_hourly_rate():
    """CASHCAT. 86 trades en 14 s -> 9,5 M$/h. C'est une rafale, pas un debit."""
    rafale = _flux_realiste(86, vol_par_trade=167.0, pas_s=0.16)   # ~14 secondes
    v = evaluer_market_making("RAFALE", rafale, spread_bps=60.0)
    assert v.pnl_par_h_usd is None
    assert "FENETRE_TROP_COURTE" in v.verdict
    assert v.volume_par_min_usd == 0.0, "aucun debit ne doit etre publie"


def test_a_long_enough_window_IS_accepted():
    """On ne refuse pas par principe : une vraie fenetre d'observation passe."""
    assert FENETRE_MIN_OBSERVATION_S >= 1800.0
    long = _flux_realiste(400, vol_par_trade=100.0, pas_s=6.0)     # 400 x 6 s = 40 min
    v = evaluer_market_making("LONG", long, spread_bps=40.0)
    assert "FENETRE_TROP_COURTE" not in v.verdict
