"""ALPHA-6 — NBBO synthétique exécutable et normalisation de carnet multi-venues.

Le test central est `test_un_ecart_de_mid_nest_jamais_un_arbitrage` : deux venues peuvent afficher des mids
très éloignés sans qu'aucune paire d'ordres ne soit exécutable. Confondre les deux fabrique un edge qui
n'existe pas.

Paper uniquement : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.cross_venue_contract import (  # noqa: E402
    BUY_HL_SELL_BINANCE,
    SELL_HL_BUY_BINANCE,
    VenueAction,
)
from hl_observer.arbitrage import nbbo_synthetique as NBBO  # noqa: E402

MAINTENANT = 1_700_000_000_000


def _brut(venue, symbole, bid, ask, *, bid_size=10.0, ask_size=10.0, recv=MAINTENANT):
    return {"venue": venue, "symbole": symbole, "bid": bid, "ask": ask,
            "bid_size": bid_size, "ask_size": ask_size, "recv_wall_ts_ms": recv}


def _quotes(*bruts):
    return NBBO.normaliser(bruts)["quotes"]


# ═══════════════ mapping versionné ═══════════════
def test_mapping_hash_stable_et_symbole_non_mappe_jamais_devine():
    assert NBBO.hash_mapping(NBBO.MAPPING_DEFAUT) == NBBO.hash_mapping(dict(NBBO.MAPPING_DEFAUT))
    assert NBBO.actif_canonique("BINANCE", "BTCUSDT") == "BTC"
    assert NBBO.actif_canonique("BINANCE", "BTCUSDC") is None      # proche mais NON déclaré
    res = NBBO.normaliser([_brut("BINANCE", "BTCUSDC", 100.0, 100.1)])
    assert res["quotes"] == [] and res["rejets"][0]["raison"] == "SYMBOLE_NON_MAPPE"


def test_changement_de_mapping_met_les_actifs_en_quarantaine():
    stable = NBBO.quarantaine_mapping(NBBO.hash_mapping(NBBO.MAPPING_DEFAUT))
    assert stable["statut"] == "STABLE" and stable["change"] is False
    change = NBBO.quarantaine_mapping("0000000000000000")
    assert change["statut"] == "QUARANTAINE" and change["change"] is True
    assert "BTC" in change["actifs_en_quarantaine"]


def test_champs_manquants_ou_carnet_invalide_sont_rejetes_sans_zero():
    res = NBBO.normaliser([
        {"venue": "HL", "symbole": "BTC", "bid": 100.0},                       # ask absent
        _brut("HL", "BTC", 0.0, 100.0),                                        # bid nul
        _brut("HL", "BTC", 101.0, 100.0),                                      # croisé localement
    ])
    raisons = [r["raison"] for r in res["rejets"]]
    assert raisons == ["CHAMPS_MANQUANTS", "CARNET_INVALIDE", "CARNET_INVALIDE"]
    assert res["quotes"] == []


# ═══════════════ fraîcheur à l'horloge courante ═══════════════
def test_venue_perimee_exclue_par_lhorloge_courante():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.1, recv=MAINTENANT - 5_000),
                     _brut("BINANCE", "BTCUSDT", 100.0, 100.1, recv=MAINTENANT))
    vivantes, exclues = NBBO.venues_fraiches(quotes, now_ms=MAINTENANT, age_max_ms=1_000)
    assert [q.venue for q in vivantes] == ["BINANCE"]
    assert exclues[0]["venue"] == "HL" and exclues[0]["raison"] == "VENUE_PERIMEE"


def test_horodatage_dans_le_futur_est_exclu():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.1, recv=MAINTENANT + 10_000))
    _, exclues = NBBO.venues_fraiches(quotes, now_ms=MAINTENANT)
    assert exclues[0]["raison"] == "HORODATAGE_DANS_LE_FUTUR"


def test_aucune_venue_fraiche_donne_un_statut_explicite():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.1, recv=MAINTENANT - 60_000))
    nb = NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT)
    assert nb["statut"] == "AUCUNE_VENUE_FRAICHE" and nb["buy_route"] is None


# ═══════════════ routes séparées ═══════════════
def test_routes_separees_achat_au_meilleur_ask_et_vente_au_meilleur_bid():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.60, ask_size=7.0),
                     _brut("BINANCE", "BTCUSDT", 100.30, 100.40, bid_size=4.0))
    nb = NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT)
    assert nb["statut"] == "OK"
    assert nb["buy_route"].venue == "BINANCE" and nb["buy_route"].prix == 100.40
    assert nb["buy_route"].action is VenueAction.BUY
    assert nb["sell_route"].venue == "BINANCE" and nb["sell_route"].prix == 100.30
    # aucune valeur de mid n'est produite par le NBBO
    assert "mid" not in nb and "mid" not in nb["buy_route"].as_dict()


def test_actifs_melanges_refuses():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.1), _brut("HL", "ETH", 50.0, 50.1))
    assert NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT)["statut"] == "ACTIFS_MELANGES"


# ═══════════════ le test central ═══════════════
def test_un_ecart_de_mid_nest_jamais_un_arbitrage():
    """Mids éloignés de ~500 bps, spreads larges : AUCUNE paire d'ordres n'est exécutable."""
    quotes = _quotes(_brut("HL", "BTC", 90.0, 110.0),          # mid 100
                     _brut("BINANCE", "BTCUSDT", 85.0, 105.0))  # mid 95
    nb = NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT)
    opp = NBBO.opportunite_executable(nb)
    assert opp["statut"] == "AUCUN_CROISEMENT" and opp["executable"] is False
    assert opp["ecart_bps"] < 0                                  # meilleur bid 90 < meilleur ask 105
    assert "mid" in opp["raison"]


def test_meilleur_bid_et_ask_sur_la_meme_venue_ne_sont_pas_un_arbitrage():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.1),
                     _brut("BINANCE", "BTCUSDT", 99.0, 101.0))
    opp = NBBO.opportunite_executable(NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT))
    assert opp["statut"] == "AUCUN_CROISEMENT_INTER_VENUES" and opp["executable"] is False


# ═══════════════ croisement réel ═══════════════
def test_croisement_reel_executable_et_borne_par_la_plus_petite_jambe():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.10, ask_size=5.0),
                     _brut("BINANCE", "BTCUSDT", 100.50, 100.60, bid_size=3.0))
    opp = NBBO.opportunite_executable(NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT))
    assert opp["statut"] == "EXECUTABLE" and opp["executable"] is True
    assert opp["buy_route"]["venue"] == "HL" and opp["buy_route"]["prix"] == 100.10
    assert opp["sell_route"]["venue"] == "BINANCE" and opp["sell_route"]["prix"] == 100.50
    assert opp["taille_appariee"] == 3.0 and opp["taille_bornee_par"] == "BINANCE"
    assert opp["net_bps"] == opp["ecart_bps"]
    assert opp["real_execution"] is False


def test_croisement_sous_les_couts_nest_pas_rentable():
    quotes = _quotes(_brut("HL", "BTC", 100.0, 100.10, ask_size=5.0),
                     _brut("BINANCE", "BTCUSDT", 100.50, 100.60, bid_size=3.0))
    opp = NBBO.opportunite_executable(NBBO.nbbo_directionnel(quotes, now_ms=MAINTENANT), cout_ar_bps=80.0)
    assert opp["statut"] == "NON_RENTABLE_APRES_COUTS" and opp["executable"] is False
    assert opp["net_bps"] < 0


def test_direction_suit_le_contrat_de_sens_du_bloc_2():
    achat_hl = _quotes(_brut("HL", "BTC", 100.0, 100.10, ask_size=5.0),
                       _brut("BINANCE", "BTCUSDT", 100.50, 100.60, bid_size=3.0))
    opp = NBBO.opportunite_executable(NBBO.nbbo_directionnel(achat_hl, now_ms=MAINTENANT))
    assert opp["direction_hl_binance"] == BUY_HL_SELL_BINANCE.as_dict()

    achat_bin = _quotes(_brut("HL", "BTC", 100.50, 100.60, bid_size=3.0),
                        _brut("BINANCE", "BTCUSDT", 100.0, 100.10, ask_size=5.0))
    opp2 = NBBO.opportunite_executable(NBBO.nbbo_directionnel(achat_bin, now_ms=MAINTENANT))
    assert opp2["direction_hl_binance"] == SELL_HL_BUY_BINANCE.as_dict()


def test_donnees_insuffisantes_ne_produisent_aucune_opportunite():
    opp = NBBO.opportunite_executable({"statut": "AUCUNE_VENUE_FRAICHE"})
    assert opp["statut"] == "DONNEES_INSUFFISANTES" and opp["executable"] is False


# ═══════════════ sécurité ═══════════════
def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "arbitrage" / "nbbo_synthetique.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans nbbo_synthetique: %s" % interdit
