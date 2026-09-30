"""Q2 -- L'ARBITRAGE SE JUGE SUR DES JAMBES EXECUTABLES.

Trois mensonges attrapes ici, chacun avec son test :

  1. LE MID. `ws_price_discrepancy_detector` (BRANCHE dans le moteur live) calculait
     `abs(a.mid - b.mid)`. On demontre par FUZZING que l'ecart de mid surestime tout arbitrage
     d'exactement `(spread_A + spread_B) / 2` -- identite algebrique, jamais une approximation.

  2. LA LIQUIDITE INVENTEE. `compute_book_costs` extrapolait au prix du dernier niveau quand le
     carnet etait trop mince : un slippage sous-estime PRECISEMENT quand il compte.

  3. LE CLASSEMENT PAR MID. `compare_cross_source_prices` prenait `min(values, key=mid)` comme
     « la moins chere ». Le mid le plus bas n'est PAS l'ask le plus bas.

Aucun ordre reel.
"""
from __future__ import annotations

import random

import pytest

from hl_observer.arbitrage.cross_source_comparator import (
    CrossSourcePrice,
    compare_cross_source_prices,
)
from hl_observer.arbitrage.executable_legs import (
    ACHAT,
    ARB_MID_SEULEMENT,
    ARB_OK,
    JAMBE_CARNET_VIDE,
    JAMBE_PROFONDEUR_INSUFFISANTE,
    JAMBE_SENS_INCONNU,
    VENTE,
    arbitrage_executable,
    edge_mid_bps,
    edge_top_of_book_bps,
    jambe_executable,
    profondeur_disponible_usd,
    surestimation_du_mid_bps,
)
from hl_observer.arbitrage.ws_price_discrepancy_detector import (
    DECISION_EXECUTABLE,
    DECISION_MID_SEULEMENT,
    detect_ws_price_discrepancies,
)
from hl_observer.collection.l2_snapshot_cache import compute_book_costs
from hl_observer.realtime.multi_source_price_stream import PriceEvent

# ============================================================ 1. LE THEOREME


def test_LE_THEOREME_le_mid_surestime_d_un_demi_spread_PAR_JAMBE():
    """edge_mid - edge_executable = (spread_A + spread_B) / 2. EXACTEMENT.

    Ce n'est pas une marge de prudence : c'est une identite. Le mid ne peut PAS sous-estimer un
    arbitrage. Il ne se trompe que dans un seul sens -- celui qui fait trader.
    """
    rng = random.Random(20260713)
    for _ in range(2_000):
        base = rng.uniform(0.01, 60_000.0)
        # deux carnets, spreads independants, ecart de prix quelconque
        a_mid = base
        b_mid = base * (1.0 + rng.uniform(-0.02, 0.02))
        demi_a = a_mid * rng.uniform(0.0, 0.004)
        demi_b = b_mid * rng.uniform(0.0, 0.004)
        a_bid, a_ask = a_mid - demi_a, a_mid + demi_a
        b_bid, b_ask = b_mid - demi_b, b_mid + demi_b
        if min(a_bid, b_bid) <= 0:
            continue

        ref = (a_mid + b_mid) / 2.0
        mid = edge_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)
        exe = edge_top_of_book_bps(a_ask=a_ask, b_bid=b_bid, reference=ref)
        surest = surestimation_du_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)

        assert mid - exe == pytest.approx(surest, abs=1e-6), (
            "l'identite algebrique est violee : le theoreme est faux ou le code ment"
        )
        assert surest >= -1e-9, "le mid SOUS-estimerait un arbitrage : impossible"


def test_le_mid_transforme_une_PERTE_en_opportunite():
    """Le cas concret, chiffre. Deux venues a 20 bps d'ecart de mid, 12 bps de spread chacune."""
    a_bid, a_ask = 99.94, 100.06     # mid 100.00, spread 12 bps
    b_bid, b_ask = 100.14, 100.26    # mid 100.20, spread 12 bps

    mid = edge_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)
    exe = edge_top_of_book_bps(a_ask=a_ask, b_bid=b_bid, reference=100.1)

    assert mid == pytest.approx(19.98, abs=0.05)   # « 20 bps ! »
    assert exe == pytest.approx(7.99, abs=0.05)    # ... 8 bps en vrai
    # Avec 12 bps de frais aller-retour, l'un fait trader, l'autre refuse.
    assert mid - 12.0 > 0.0
    assert exe - 12.0 < 0.0


# ============================================================ 2. UNE JAMBE


def test_la_jambe_traverse_le_carnet_et_rend_le_VWAP_pas_le_top():
    # 500 $ : 100 $ a 10.0, puis 400 $ a 10.1  ->  VWAP > 10.0
    asks = [(10.0, 10.0), (10.1, 100.0)]
    j = jambe_executable(asks, sens=ACHAT, notional_usd=500.0)
    assert j.executable
    assert j.meilleur_prix == 10.0
    assert j.prix_moyen > 10.0, "on aurait paye le top-of-book pour tout : liquidite inventee"
    assert j.slippage_bps > 0.0
    assert j.niveaux_traverses == 2


def test_la_jambe_REFUSE_quand_le_carnet_ne_peut_PAS_absorber():
    """🔴 LE BUG. L'ancien code extrapolait au dernier niveau : liquidite infinie a prix fixe."""
    asks = [(10.0, 1.0), (10.1, 1.0)]        # ~20 $ visibles
    j = jambe_executable(asks, sens=ACHAT, notional_usd=500.0)
    assert not j.executable
    assert j.raison == JAMBE_PROFONDEUR_INSUFFISANTE
    assert j.prix_moyen is None, "un prix rendu ici serait un prix INVENTE"
    assert j.notional_disponible_usd == pytest.approx(20.1, abs=0.01)


def test_le_slippage_est_un_COUT_dans_les_DEUX_sens():
    """A la VENTE on encaisse MOINS que le meilleur bid. Un slippage negatif serait un cadeau."""
    bids = [(10.0, 10.0), (9.9, 100.0)]
    j = jambe_executable(bids, sens=VENTE, notional_usd=500.0)
    assert j.executable
    assert j.meilleur_prix == 10.0
    assert j.prix_moyen < 10.0
    assert j.slippage_bps > 0.0


def test_l_ordre_de_traversee_est_IMPOSE_pas_fait_confiance_a_l_appelant():
    """Un carnet ask mal trie ne doit pas nous faire manger le niveau cher en premier."""
    a = jambe_executable([(10.1, 100.0), (10.0, 10.0)], sens=ACHAT, notional_usd=200.0)
    b = jambe_executable([(10.0, 10.0), (10.1, 100.0)], sens=ACHAT, notional_usd=200.0)
    assert a.prix_moyen == pytest.approx(b.prix_moyen)
    assert a.meilleur_prix == 10.0


def test_carnet_vide_ou_sens_inconnu_REFUSENT():
    assert jambe_executable([], sens=ACHAT, notional_usd=100.0).raison == JAMBE_CARNET_VIDE
    assert jambe_executable(None, sens=ACHAT, notional_usd=100.0).raison == JAMBE_CARNET_VIDE
    assert jambe_executable([(1.0, 1.0)], sens="PEUT-ETRE", notional_usd=1.0).raison == JAMBE_SENS_INCONNU
    assert not jambe_executable([(1.0, 1.0)], sens=ACHAT, notional_usd=0.0).executable
    assert not jambe_executable([(1.0, 1.0)], sens=ACHAT, notional_usd=float("nan")).executable


def test_profondeur_disponible_ignore_les_niveaux_pourris():
    assert profondeur_disponible_usd([(10.0, 2.0), (0.0, 5.0), (-1.0, 5.0), (9.0, 0.0)]) == 20.0
    assert profondeur_disponible_usd(None) == 0.0


# ============================================================ 3. L'ARBITRAGE COMPLET


def _carnet(mid: float, demi_spread: float, taille: float):
    return ([(mid - demi_spread, taille)], [(mid + demi_spread, taille)])


def test_l_arbitrage_rend_AUSSI_le_chiffre_mensonger_pour_qu_on_le_voie():
    bids_a, asks_a = _carnet(100.0, 0.06, 1_000.0)
    bids_b, asks_b = _carnet(100.2, 0.06, 1_000.0)
    r = arbitrage_executable(
        coin="BTC", source_a="hl", bids_a=bids_a, asks_a=asks_a,
        source_b="cex", bids_b=bids_b, asks_b=asks_b,
        notional_usd=500.0, frais_bps=12.0, min_edge_net_bps=0.0,
    )
    assert r.source_achat == "hl" and r.source_vente == "cex"
    assert r.edge_sur_le_mid_bps == pytest.approx(19.98, abs=0.1)
    assert r.edge_brut_bps == pytest.approx(7.99, abs=0.1)
    assert r.surestimation_du_mid_bps == pytest.approx(11.99, abs=0.1)
    assert r.edge_net_bps < 0.0
    assert not r.executable
    assert r.raison == ARB_MID_SEULEMENT, (
        "le mid criait opportunite, la realite dit non : c'est CE cas qu'il faut nommer"
    )


def test_l_arbitrage_accepte_quand_il_est_VRAIMENT_la():
    bids_a, asks_a = _carnet(100.0, 0.01, 1_000.0)      # spreads serres
    bids_b, asks_b = _carnet(101.0, 0.01, 1_000.0)      # 100 bps d'ecart
    r = arbitrage_executable(
        coin="BTC", source_a="hl", bids_a=bids_a, asks_a=asks_a,
        source_b="cex", bids_b=bids_b, asks_b=asks_b,
        notional_usd=500.0, frais_bps=12.0, min_edge_net_bps=0.0,
    )
    assert r.executable and r.raison == ARB_OK
    assert r.edge_net_bps > 80.0


def test_l_arbitrage_essaie_les_DEUX_sens():
    """Si B est le moins cher, on achete B. Le code ne doit pas presumer du sens."""
    bids_a, asks_a = _carnet(101.0, 0.01, 1_000.0)
    bids_b, asks_b = _carnet(100.0, 0.01, 1_000.0)
    r = arbitrage_executable(
        coin="BTC", source_a="hl", bids_a=bids_a, asks_a=asks_a,
        source_b="cex", bids_b=bids_b, asks_b=asks_b,
        notional_usd=500.0, frais_bps=0.0,
    )
    assert r.executable
    assert r.source_achat == "cex" and r.source_vente == "hl"


def test_l_arbitrage_REFUSE_si_une_jambe_n_est_pas_profonde():
    bids_a, asks_a = _carnet(100.0, 0.01, 0.5)         # ~50 $ dispo seulement
    bids_b, asks_b = _carnet(101.0, 0.01, 1_000.0)
    r = arbitrage_executable(
        coin="BTC", source_a="hl", bids_a=bids_a, asks_a=asks_a,
        source_b="cex", bids_b=bids_b, asks_b=asks_b,
        notional_usd=500.0, frais_bps=0.0,
    )
    assert not r.executable
    assert JAMBE_PROFONDEUR_INSUFFISANTE in r.reason_codes
    assert r.edge_net_bps is None, "un edge chiffre ici serait calcule sur un trade impossible"


def test_une_seule_source_n_est_pas_un_arbitrage():
    b, a = _carnet(100.0, 0.01, 1_000.0)
    r = arbitrage_executable(coin="BTC", source_a="hl", bids_a=b, asks_a=a,
                             source_b="HL", bids_b=b, asks_b=a, notional_usd=500.0)
    assert not r.executable


def test_l_arbitrage_ne_pretend_JAMAIS_a_une_execution_reelle():
    b, a = _carnet(100.0, 0.01, 1_000.0)
    b2, a2 = _carnet(101.0, 0.01, 1_000.0)
    r = arbitrage_executable(coin="BTC", source_a="hl", bids_a=b, asks_a=a,
                             source_b="cex", bids_b=b2, asks_b=a2, notional_usd=500.0)
    assert r.paper_only is True
    assert r.as_dict()["real_execution"] is False


# ============================================================ 4. LE DETECTEUR BRANCHE EN LIVE


def test_le_detecteur_LIVE_ne_declenche_plus_sur_un_mirage_du_mid():
    """20 bps d'ecart de mid, 12 bps de spread chacun -> 8 bps reels. Seuil a 15 bps.

    ANCIEN CODE : 1 opportunite (il voyait 20).
    NOUVEAU     : 0 opportunite -- et le mirage reste TRACABLE pour l'audit.
    """
    ev = [
        PriceEvent("hl", "HYPE", 99.94, 100.06, 1),
        PriceEvent("cex", "HYPE", 100.14, 100.26, 1),
    ]
    assert detect_ws_price_discrepancies(ev, min_spread_bps=15.0) == ()

    trace = detect_ws_price_discrepancies(ev, min_spread_bps=15.0, executables_seulement=False)
    assert len(trace) == 1
    d = trace[0]
    assert d.decision == DECISION_MID_SEULEMENT
    assert not d.executable
    assert d.spread_bps == pytest.approx(19.98, abs=0.1)          # ce qu'on VOYAIT
    assert d.edge_executable_bps == pytest.approx(7.99, abs=0.1)  # ce qu'on AURAIT eu
    assert d.surestimation_du_mid_bps == pytest.approx(11.99, abs=0.1)


def test_le_detecteur_LIVE_trouve_encore_un_VRAI_ecart():
    ev = [
        PriceEvent("hl", "HYPE", 99.99, 100.01, 1),
        PriceEvent("cex", "HYPE", 100.99, 101.01, 1),
    ]
    rows = detect_ws_price_discrepancies(ev, min_spread_bps=50.0)
    assert len(rows) == 1
    r = rows[0]
    assert r.decision == DECISION_EXECUTABLE and r.executable
    assert r.source_achat == "hl" and r.source_vente == "cex"
    assert r.prix_achat == 100.01 and r.prix_vente == 100.99


def test_le_detecteur_LIVE_donne_le_SENS_pas_une_valeur_absolue():
    """`abs()` rendait le meme chiffre dans les deux sens. Un arbitrage a une DIRECTION."""
    ev = [
        PriceEvent("cex", "HYPE", 100.99, 101.01, 1),   # le plus CHER, en premier
        PriceEvent("hl", "HYPE", 99.99, 100.01, 1),
    ]
    r = detect_ws_price_discrepancies(ev, min_spread_bps=50.0)[0]
    assert r.source_achat == "hl", "on doit ACHETER la venue la moins chere, peu importe l'ordre"
    assert r.source_vente == "cex"


def test_le_test_historique_ne_passait_QUE_parce_que_le_spread_etait_ZERO():
    """PriceEvent("hl","HYPE",100,100,1) : bid == ask. Un carnet qui n'existe pas.

    Quand bid == ask, mid == bid == ask : le mid ne ment pas. C'etait le SEUL cas ou l'ancien
    code etait juste, et c'est exactement celui qu'on testait. Le nouveau code le passe aussi --
    mais lui, il passe aussi les autres.
    """
    rows = detect_ws_price_discrepancies(
        [PriceEvent("hl", "HYPE", 100, 100, 1), PriceEvent("cex", "HYPE", 101, 101, 1)],
        min_spread_bps=50,
    )
    assert len(rows) == 1
    assert rows[0].decision == DECISION_EXECUTABLE
    assert rows[0].edge_executable_bps == pytest.approx(rows[0].spread_bps, abs=1e-6)


# ============================================================ 5. LE CARNET NE MENT PLUS


def test_compute_book_costs_n_EXTRAPOLE_PLUS_au_dernier_niveau():
    """🔴 LE BUG. `qty += remain_usd / levels_ask[-1][0]` = liquidite infinie a prix fixe."""
    bids = [(9.99, 1.0)]
    asks = [(10.0, 1.0), (10.1, 1.0)]        # ~20 $ visibles
    assert compute_book_costs(bids, asks, notional_usd=10.0) is not None   # ca rentre
    assert compute_book_costs(bids, asks, notional_usd=5_000.0) is None, (
        "le carnet ne peut pas absorber 5 000 $ : rendre un cout ici, c'est l'inventer"
    )


def test_compute_book_costs_reste_juste_quand_le_carnet_SUFFIT():
    bids = [(9.99, 1_000.0)]
    asks = [(10.0, 10.0), (10.1, 1_000.0)]
    out = compute_book_costs(bids, asks, notional_usd=500.0)
    assert out is not None
    spread_bps, slip_bps = out
    assert spread_bps > 0.0
    assert slip_bps > 0.0, "on traverse 2 niveaux : le slippage ne peut pas etre nul"


# ============================================================ 6. LE CLASSEMENT PAR MID


def test_le_mid_le_plus_bas_n_est_PAS_l_ask_le_plus_bas():
    """La faute la plus sournoise : classer les venues sur un prix qu'on ne paye pas.

    A : mid 100.00, spread LARGE  -> ask 100.50
    B : mid 100.20, spread ETROIT -> ask 100.21   <-- MOINS CHER a l'achat, malgre un mid PLUS HAUT
    """
    rows = compare_cross_source_prices([
        CrossSourcePrice("A", "HYPE", 99.50, 100.50),
        CrossSourcePrice("B", "HYPE", 100.19, 100.21),
    ])
    assert len(rows) == 1
    r = rows[0]
    assert r.low_source == "A", "le mid designe A comme la moins chere..."
    assert r.source_achat == "B", "...mais on achete a l'ASK, et c'est B qui est moins cher"
    assert r.prix_achat == 100.21
    assert r.prix_vente == 100.19          # meilleur bid = celui de B aussi
    assert r.edge_executable_bps < 0.0     # acheter et vendre sur B : on perd le spread
    assert not r.executable
