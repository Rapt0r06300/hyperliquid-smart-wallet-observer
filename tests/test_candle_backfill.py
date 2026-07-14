"""🔴 « DATA-LIMITED » ÉTAIT UNE BLESSURE AUTO-INFLIGÉE (2026-07-13).

Depuis des jours, chaque mesure meurt sur « data-limited » : #242 (18,9 h d'historique), la
recherche 150 M (horizons de 8 h sur 19 h de donnees), la purge H-05 (qui vide le train).

Et pendant ce temps, `build_candle_snapshot_payload(coin, interval, **start_time**, end_time)`
etait **DEJA ecrit**, **DEJA autorise** -- et on ne s'en servait que pour les bougies **recentes**.

    On peut telecharger des MOIS d'historique de prix. Gratuitement. Depuis l'API qu'on
    interroge tous les jours.

*Une capacite presente, un chainon manquant, personne qui se plaint.* **La maladie du projet dans
sa version la plus chere : elle nous a fait declarer « impossible a mesurer » ce qui etait a un
appel de distance.**

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.collection.candle_backfill import (
    MAX_BOUGIES_PAR_REQUETE,
    Bougie,
    IntervalleInconnu,
    couverture,
    dedupliquer,
    minutes_de,
    parser_bougies,
    plan_de_requetes,
)


def _row(t: int, o=100.0, h=101.0, lo=99.0, c=100.5, v=10.0, s="BTC"):
    return {"t": t, "T": t + 59_999, "s": s, "i": "1m",
            "o": str(o), "h": str(h), "l": str(lo), "c": str(c), "v": str(v), "n": 5}


# ============================================================ 1. LE PLAN DE PAGINATION


def test_le_plan_DECOUPE_pour_ne_JAMAIS_depasser_la_borne_de_l_API():
    """🔴 SANS DECOUPAGE, L'API RENVOIE UNE REPONSE **TRONQUEE SANS LE DIRE**.

    On aurait alors un trou dans l'historique -- silencieux. *Le pire bug est celui qui ne plante
    pas.* (Le poller L2, le stall a 02:32, le « maintenant » gele : toujours la meme famille.)
    """
    jour = 24 * 3_600_000
    fenetres = plan_de_requetes(debut_ms=0, fin_ms=30 * jour, intervalle="1m")
    assert len(fenetres) > 1, "30 jours en 1m ne tiennent PAS dans une seule requete"
    pas_max = MAX_BOUGIES_PAR_REQUETE * 60_000
    for d, f in fenetres:
        assert 0 < f - d <= pas_max, "une fenetre depasse la borne de l'API : reponse tronquee"
    # les fenetres se SUIVENT sans trou
    for i in range(1, len(fenetres)):
        assert fenetres[i][0] == fenetres[i - 1][1]
    assert fenetres[0][0] == 0
    assert fenetres[-1][1] == 30 * jour


def test_un_intervalle_INCONNU_est_REFUSE_pas_devine():
    """*On ne devine pas la duree d'un intervalle qu'on ne connait pas.*"""
    with pytest.raises(IntervalleInconnu):
        minutes_de("7m")
    with pytest.raises(IntervalleInconnu):
        plan_de_requetes(debut_ms=0, fin_ms=10, intervalle="banane")


def test_un_intervalle_VIDE_ou_INVERSE_ne_produit_AUCUNE_requete():
    assert plan_de_requetes(debut_ms=100, fin_ms=100, intervalle="1m") == []
    assert plan_de_requetes(debut_ms=200, fin_ms=100, intervalle="1m") == []


# ============================================================ 2. DENY-BY-DEFAULT AU PARSING


def test_une_bougie_BIEN_FORMEE_est_lue():
    b = parser_bougies("BTC", [_row(1_000_000)])
    assert len(b) == 1
    assert b[0].open == pytest.approx(100.0)
    assert b[0].close == pytest.approx(100.5)
    assert b[0].coin == "BTC"


@pytest.mark.parametrize("casse", [
    {},                                             # vide
    {"t": "pas un int", "o": "1", "h": "1", "l": "1", "c": "1"},
    {"t": 1, "o": "0", "h": "1", "l": "1", "c": "1"},        # prix NUL
    {"t": 1, "o": "-5", "h": "1", "l": "1", "c": "1"},       # prix NEGATIF
    {"t": 1, "o": "1", "h": "1", "l": "9", "c": "1"},        # high < low : incoherent
    "pas un dict",
])
def test_une_bougie_CASSEE_est_ECARTEE_jamais_devinee(casse):
    """🔴 *Un `o=0` invente pourrirait TOUS les rendements en aval -- et personne ne le verrait.*"""
    assert parser_bougies("BTC", [casse]) == []


def test_un_payload_qui_n_est_PAS_une_liste_ne_plante_pas():
    assert parser_bougies("BTC", None) == []
    assert parser_bougies("BTC", {"erreur": "rate limited"}) == []


# ============================================================ 3. LA DEDUPLICATION


def test_les_fenetres_qui_se_CHEVAUCHENT_ne_DOUBLENT_pas_l_historique():
    """*Un volume double fausserait toute mesure de liquidite* -- et le pire, c'est qu'il aurait
    l'air plausible."""
    b = parser_bougies("BTC", [_row(1000), _row(2000)])
    b += parser_bougies("BTC", [_row(2000), _row(3000)])     # chevauchement au bord
    d = dedupliquer(b)
    assert len(d) == 3
    assert [x.t_ms for x in d] == [1000, 2000, 3000]


# ============================================================ 4. 🔴 LES TROUS SE DISENT


def test_un_TROU_dans_l_historique_est_COMPTE_et_ANNONCE():
    """🔴 UN HISTORIQUE AVEC DES TROUS N'EST PAS UN HISTORIQUE.

    Un trou silencieux, c'est une periode ou le marche a bouge et ou notre backtest croit qu'il
    ne s'est **rien passe**. C'est une donnee FABRIQUEE par omission.
    """
    m = 60_000
    b = parser_bougies("BTC", [_row(0), _row(m), _row(5 * m)])   # il manque t=2m,3m,4m
    cv = couverture(b, intervalle="1m")
    assert cv is not None
    assert cv.n_bougies == 3
    assert cv.n_trous == 3, "les 3 minutes manquantes ne sont pas signalees"


def test_un_historique_COMPLET_n_annonce_AUCUN_trou():
    m = 60_000
    b = parser_bougies("BTC", [_row(i * m) for i in range(10)])
    cv = couverture(b, intervalle="1m")
    assert cv is not None and cv.n_trous == 0
    assert cv.heures == pytest.approx(9 / 60.0, rel=0.01)


def test_aucune_bougie_donne_None_pas_une_couverture_INVENTEE():
    """Etat vide HONNETE. Rendre une couverture de 0 h laisserait croire qu'on a regarde."""
    assert couverture([], intervalle="1m") is None


# ============================================================ 5. CE QUE CA NE DEBLOQUE PAS


def test_le_module_DIT_ce_qu_il_ne_debloque_PAS():
    """⚠️ L'HONNETETE OBLIGATOIRE.

    Les bougies debloquent tout ce qui depend du PRIX. Elles ne donnent **NI le carnet L2** (donc
    T1b reste sur ses 9 543 snapshots), **NI les trades avec agresseur** (donc la selection
    adverse reste limitee au live).

    *Annoncer que « le probleme de donnees est resolu » serait FAUX. Il est resolu POUR LES PRIX.*
    Un module qui laisserait croire le contraire serait une promesse -- interdite.
    """
    import inspect

    from hl_observer.collection import candle_backfill as mod

    doc = inspect.getdoc(mod) or ""
    assert "NE DEBLOQUE" in doc
    assert "carnet L2" in doc
    assert "agresseur" in doc
    assert "T1b" in doc


def test_une_bougie_porte_sa_cle_de_DEDUPLICATION():
    b = Bougie(coin="BTC", t_ms=42, open=1, high=2, low=0.5, close=1.5, volume=10)
    assert b.cle == ("BTC", 42)
