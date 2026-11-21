"""Le portefeuille d'un compte Hyperliquid : aucun chiffre invente, aucune portee confondue.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a montre que ce module n'etait atteint par
AUCUN test, meme indirectement : il fabrique pourtant l'instantane de portefeuille qui sert de
cible a la replication d'inventaire. Un module qui calcule une exposition et un levier sans
aucun test peut se tromper d'un facteur sans que rien ne rougisse.

Ce qui est verifie ici est ce que le module PROMET dans son en-tete :
  * les deux formes du meme etat (WebSocket imbrique / REST a plat) donnent le meme resultat ;
  * une position illisible invalide TOUT l'instantane -- jamais un zero favorable ;
  * un compte sans position rend une liste VIDE, pas une absence de ligne ;
  * la portee par dex n'est jamais lue comme le portefeuille entier du compte ;
  * lecture seule : `read_only` vrai et `real_execution` faux, toujours.
"""
from __future__ import annotations

import math

import pytest

from hl_observer.collection.portefeuille_compte import (
    SCHEMA_PORTEFEUILLE,
    construire_portefeuille,
    etat_du_compte,
    nombre,
)

USER = "0xABCdef0000000000000000000000000000000001"


def _position(coin="BTC", szi="1.5", valeur="150000", upnl="12.5", entry="99000", levier=10):
    return {"position": {"coin": coin, "szi": szi, "positionValue": valeur,
                         "unrealizedPnl": upnl, "entryPx": entry,
                         "leverage": {"value": levier, "type": "cross"}}}


def _etat(positions, nav="20000", time_ms=1_700_000_000_000):
    return {"assetPositions": positions, "marginSummary": {"accountValue": nav},
            "time": time_ms}


# ------------------------------------------------------------------ nombre()
@pytest.mark.parametrize("brut", [None, True, False, "abc", float("inf"), float("-inf"),
                                  float("nan"), {}, [], object()])
def test_nombre_refuse_tout_ce_qui_n_est_pas_un_nombre_fini(brut):
    """Un booleen qui passerait pour 1.0, un inf qui empoisonne un ratio : tous refuses."""
    assert nombre(brut) is None


@pytest.mark.parametrize("brut,attendu", [("1.5", 1.5), (2, 2.0), (-0.25, -0.25), ("0", 0.0)])
def test_nombre_accepte_les_formes_reelles_de_l_api(brut, attendu):
    """L'API Hyperliquid rend ses nombres en CHAINES : les refuser viderait tout l'instantane."""
    assert nombre(brut) == attendu


# ------------------------------------------------------------------ etat_du_compte()
def test_les_deux_formes_du_meme_etat_sont_reconnues():
    plat = _etat([])
    assert etat_du_compte(plat) is plat
    assert etat_du_compte({"clearinghouseState": plat, "dex": "", "user": USER}) is plat


@pytest.mark.parametrize("brut", [None, 5, "x", [], {}, {"autre": 1},
                                  {"assetPositions": "pas une liste"}])
def test_un_message_qui_n_est_pas_un_etat_est_refuse(brut):
    assert etat_du_compte(brut) is None


# ------------------------------------------------------------------ l'instantane
def test_les_deux_sources_donnent_le_meme_portefeuille():
    """WS imbrique et REST a plat decrivent le MEME compte : ils doivent coincider."""
    etat = _etat([_position()])
    a = construire_portefeuille(etat, user=USER, recv_ms=1_000, dex="")
    b = construire_portefeuille({"clearinghouseState": etat, "dex": "", "user": USER},
                                user=USER, recv_ms=1_000)
    assert a == b


def test_une_position_illisible_invalide_TOUT_l_instantane():
    """LA REGLE DU PROJET : une donnee contradictoire refuse, elle ne rend pas un zero favorable.

    Garder les positions lisibles et jeter l'autre donnerait une exposition SOUS-ESTIMEE,
    c'est-a-dire un risque qu'on croit plus petit qu'il n'est.
    """
    for cassee in ({"position": None}, {"position": {"coin": "", "szi": "1"}},
                   {"position": {"coin": "BTC", "szi": "pas un nombre"}},
                   {"position": {"coin": "BTC"}}, "pas un dict"):
        etat = _etat([_position(), cassee])
        assert construire_portefeuille(etat, user=USER, recv_ms=1, dex="") is None


def test_un_compte_sans_position_rend_une_liste_vide_pas_une_absence():
    snap = construire_portefeuille(_etat([]), user=USER, recv_ms=1, dex="")
    assert snap is not None
    assert snap["positions"] == [] and snap["n_positions"] == 0
    assert snap["expo_brute_usd"] == 0.0 and snap["expo_nette_usd"] == 0.0


def test_une_position_fermee_n_entre_pas_dans_l_inventaire():
    """`szi == 0` est une ligne residuelle : la compter gonflerait le nombre de positions."""
    snap = construire_portefeuille(_etat([_position(szi="0", valeur="0")]),
                                   user=USER, recv_ms=1, dex="")
    assert snap["n_positions"] == 0


def test_le_sens_de_l_exposition_nette_est_correct():
    """Un short doit SOUSTRAIRE : un signe faux ferait passer un portefeuille neutre pour long."""
    long_seul = construire_portefeuille(_etat([_position(szi="1", valeur="100")]),
                                        user=USER, recv_ms=1, dex="")
    short_seul = construire_portefeuille(_etat([_position(szi="-1", valeur="100")]),
                                         user=USER, recv_ms=1, dex="")
    assert long_seul["expo_nette_usd"] == 100.0
    assert short_seul["expo_nette_usd"] == -100.0
    assert long_seul["expo_brute_usd"] == short_seul["expo_brute_usd"] == 100.0


def test_le_levier_est_brute_sur_nav_et_refuse_sans_nav():
    """Pas de NAV = pas de levier. Jamais une division par zero, jamais un ratio invente."""
    snap = construire_portefeuille(_etat([_position(szi="1", valeur="40000")], nav="20000"),
                                   user=USER, recv_ms=1, dex="")
    assert snap["levier"] == 2.0
    for nav in (None, "0", "-5", "pas un nombre"):
        sans = construire_portefeuille(_etat([_position()], nav=nav), user=USER, recv_ms=1,
                                       dex="")
        assert sans["levier"] is None


def test_la_portee_par_dex_n_est_jamais_le_portefeuille_entier():
    """Un compte a UN etat PAR DEX : confondre les deux ferait croire un compte vide."""
    principal = construire_portefeuille(_etat([_position()]), user=USER, recv_ms=1, dex="")
    hip3 = construire_portefeuille(_etat([_position()]), user=USER, recv_ms=1, dex="xyz")
    assert principal["portfolio_scope"] == "DEX_PRINCIPAL"
    assert hip3["portfolio_scope"] == "DEX:xyz"


def test_la_portee_du_message_est_prise_quand_l_appelant_ne_la_donne_pas():
    snap = construire_portefeuille({"clearinghouseState": _etat([_position()]), "dex": "xyz"},
                                   user=USER, recv_ms=1)
    assert snap["dex"] == "xyz" and snap["portfolio_scope"] == "DEX:xyz"


def test_sans_adresse_il_n_y_a_pas_d_instantane():
    """Un instantane sans proprietaire ne peut etre rattache a rien : il ne doit pas exister."""
    for user in ("", "   ", None):
        assert construire_portefeuille(_etat([_position()]), user=user, recv_ms=1, dex="") is None


def test_l_adresse_est_normalisee_en_minuscules():
    """Deux casses de la meme adresse doivent donner UNE cle, pas deux portefeuilles."""
    snap = construire_portefeuille(_etat([]), user=USER, recv_ms=1, dex="")
    assert snap["vault"] == USER.lower()


def test_l_instantane_est_marque_lecture_seule_et_jamais_executable():
    """Invariant de SECURITE du depot : aucune donnee produite ici ne peut passer pour un ordre."""
    snap = construire_portefeuille(_etat([_position()]), user=USER, recv_ms=1, dex="")
    assert snap["read_only"] is True
    assert snap["real_execution"] is False
    assert snap["data_origin"] == "REAL_OBSERVED"
    assert snap["schema_version"] == SCHEMA_PORTEFEUILLE


def test_aucun_NaN_ni_Inf_ne_sort_de_l_instantane():
    """Un NaN dans un PnL empoisonne silencieusement tout le calcul en aval."""
    snap = construire_portefeuille(
        _etat([_position(upnl="nan", valeur="inf", entry="nan")]), user=USER, recv_ms=1, dex="")
    assert snap is not None
    for cle, valeur in snap.items():
        if isinstance(valeur, float):
            assert math.isfinite(valeur), f"{cle} = {valeur}"
    for pos in snap["positions"]:
        for cle, valeur in pos.items():
            if isinstance(valeur, float):
                assert math.isfinite(valeur), f"positions.{cle} = {valeur}"
