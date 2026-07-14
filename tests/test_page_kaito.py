"""LA PAGE DE PROGRESSION NE DOIT PAS MENTIR NON PLUS (2026-07-12).

Une UI est un endroit ou l'on ment sans le vouloir : une barre qui avance donne l'impression que
quelque chose se passe, un "bientot" rassure, un chiffre arrondi devient une promesse.

Ces tests verrouillent trois choses :
  * l'ETA se calcule sur le debit REELLEMENT observe -- jamais sur un espoir ;
  * sans aucun fill, l'ETA est `None` ("on ne sait pas"), PAS "bientot" ;
  * la page dit clairement quand les 4 h ne suffiront PAS, au lieu de laisser croire.

C'est le meme principe que le moteur : deny-by-default, jusque dans l'affichage.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.backtesting.market_making_flow import (
    FENETRE_MIN_OBSERVATION_S,
    MIN_TRADES,
    MIN_TRADES_POUR_CONCLURE,
)
from tools.page_kaito import progression


def _trades(n: int) -> list[dict]:
    return [{"coin": "KAITO", "ts": 1000.0 + i, "px": 1.0, "sz": 1.0,
             "aggressor": "BUY", "notional_usd": 100.0} for i in range(n)]


def test_sans_aucun_fill_l_eta_est_INCONNU_pas_bientot():
    """LE TEST QUI COMPTE. Extrapoler depuis zero, c'est inventer un nombre -- exactement ce
    qu'on vient de retirer du moteur. L'UI ne doit pas le reintroduire."""
    p = progression(_trades(10), fenetre_s=600.0, fills_derriere=0)
    assert p["eta_verdict_s"] is None
    assert p["verdict_atteignable_dans_la_fenetre"] is None


def test_l_eta_se_calcule_sur_le_debit_observe():
    """60 fills en 30 min = 2 fills/min. Il en manque 240 -> 120 min."""
    p = progression(_trades(240), fenetre_s=1800.0, fills_derriere=60)
    assert p["debit_fills_par_min"] == 2.0
    assert p["eta_verdict_s"] == 120 * 60


def test_la_page_DIT_quand_les_4h_ne_suffiront_pas():
    """Un debit derisoire ne doit pas etre maquille en 'ca arrive'. C'est une REPONSE :
    le marche est trop peu echange."""
    # 3 fills en 60 min -> 0,05 fill/min -> il faudrait ~99 h pour 300 fills
    p = progression(_trades(12), fenetre_s=3600.0, fills_derriere=3,
                    duree_ecoute_s=4 * 3600.0, ecoule_s=3600.0)
    assert p["eta_verdict_s"] is not None
    assert p["verdict_atteignable_dans_la_fenetre"] is False


def test_un_debit_suffisant_est_annonce_comme_atteignable():
    p = progression(_trades(2000), fenetre_s=1800.0, fills_derriere=280,
                    duree_ecoute_s=4 * 3600.0, ecoule_s=1800.0)
    assert p["verdict_atteignable_dans_la_fenetre"] is True


def test_les_trois_verrous_sont_TOUS_exiges_pour_conclure():
    """Le verdict n'existe que si les 3 sont franchis. Aucun ne se rattrape."""
    ok = dict(fenetre_s=FENETRE_MIN_OBSERVATION_S + 1, fills_derriere=MIN_TRADES_POUR_CONCLURE)

    assert progression(_trades(MIN_TRADES), **ok)["conclusif"] is True

    # fenetre trop courte -> une rafale n'est pas un debit
    assert progression(_trades(MIN_TRADES), fenetre_s=60.0,
                       fills_derriere=MIN_TRADES_POUR_CONCLURE)["conclusif"] is False
    # pas assez de fills a la borne qui compte
    assert progression(_trades(MIN_TRADES), fenetre_s=FENETRE_MIN_OBSERVATION_S + 1,
                       fills_derriere=MIN_TRADES_POUR_CONCLURE - 1)["conclusif"] is False
    # pas assez de trades du tout
    assert progression(_trades(MIN_TRADES - 1), **ok)["conclusif"] is False


def test_un_verrou_franchi_est_a_100_pourcent_pas_plus():
    """Une barre qui deborde donnerait l'illusion d'une marge qu'on n'a pas."""
    p = progression(_trades(10_000), fenetre_s=99_999.0, fills_derriere=99_999)
    for v in p["verrous"]:
        assert 0.0 <= v["pct"] <= 100.0


def test_la_page_se_rend_sans_planter_meme_sans_donnee():
    """Une UI qui plante quand il n'y a rien a montrer, c'est une UI qui cache l'etat vide."""
    from tools.page_kaito import rendre_html

    page = rendre_html()
    assert "KAITO" in page
    assert "aucune signature" in page          # la ligne de securite est TOUJOURS la
