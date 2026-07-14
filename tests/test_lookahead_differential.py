"""G1 -- LE TEST DIFFERENTIEL DOIT SAVOIR ATTRAPER UNE VRAIE FUITE.

Un detecteur qui ne dit jamais « fuite » ne detecte rien. Avant de croire son verdict « propre »
sur la vraie recherche, on lui donne un TRICHEUR : un selecteur qui regarde ouvertement le futur.
S'il ne l'attrape pas, son OK ne vaut rien.

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.lookahead_differential import (
    FUITE_SELECTION_DEPEND_DU_FUTUR,
    FUTUR_BROUILLE,
    FUTUR_EFFACE,
    FUTUR_INVERSE,
    selection_invariante_au_futur,
    torturer_les_marks,
)

CANDIDATS = [
    {"coin": "BTC", "direction": "LONG", "recorded_at": 1000.0, "current_mid": 100.0},
    {"coin": "BTC", "direction": "SHORT", "recorded_at": 1010.0, "current_mid": 101.0},
    {"coin": "ETH", "direction": "LONG", "recorded_at": 1020.0, "current_mid": 50.0},
]
MARKS = {
    "BTC": [(900.0, 99.0), (1005.0, 100.5), (1100.0, 110.0), (1200.0, 120.0)],
    "ETH": [(950.0, 49.0), (1050.0, 52.0), (1150.0, 40.0)],
}


# ====================================================== LE DETECTEUR SAIT-IL DETECTER ?


def test_un_selecteur_TRICHEUR_est_ATTRAPE():
    """LE test qui valide le detecteur. Ce selecteur n'accepte un trade que s'il GAGNE --
    autrement dit il regarde le futur. C'est la fuite la plus grossiere possible."""

    def tricheur(candidats, marks):
        out = []
        for c in candidats:
            chemin = marks.get(c["coin"], [])
            futur = [m for (t, m) in chemin if t > float(c["recorded_at"])]
            if not futur:
                continue
            gagne = (futur[-1] > float(c["current_mid"])) if c["direction"] == "LONG" \
                else (futur[-1] < float(c["current_mid"]))
            if gagne:                       # <-- IL LIT LE FUTUR
                out.append(c)
        return out

    v = selection_invariante_au_futur(tricheur, CANDIDATS, MARKS)
    assert v.propre is False, "un tricheur EVIDENT n'a pas ete attrape : le detecteur est inutile"
    assert v.raison == FUITE_SELECTION_DEPEND_DU_FUTUR
    assert v.ecarts, "aucune torture n'a fait bouger le tricheur : impossible"
    assert v.exemples
    # Et surtout : il doit etre attrape par une torture qui GARDE le futur (brouille/inverse).
    # S'il n'etait attrape QUE par FUTUR_EFFACE, on ne saurait pas distinguer la triche de la
    # simple non-mesurabilite -- et le detecteur serait inutile.
    assert v.lookahead is True, (
        "le tricheur n'est attrape que par l'EFFACEMENT du futur : le detecteur confond "
        "LOOKAHEAD et SURVIVANCE, donc il ne prouve rien"
    )


def test_le_detecteur_NE_CONFOND_PAS_survivance_et_lookahead():
    """🚩 MON PREMIER OUTIL CRIAIT « FUITE » SUR LA VRAIE RECHERCHE. Il avait TORT.

    Un selecteur peut avoir besoin d'un mark futur pour MESURER un trade (sinon : pas de PnL).
    Effacer le futur le fait donc refuser -- ce n'est PAS lire le futur, c'est ne pas pouvoir
    le mesurer. Confondre les deux, c'est jeter un resultat valide : une fausse alarme est
    aussi grave qu'un faux OK.
    """

    def honnete_mais_a_besoin_d_un_futur(candidats, marks):
        out = []
        for c in candidats:
            futur = [m for (t, m) in marks.get(c["coin"], []) if t > float(c["recorded_at"])]
            if not futur:
                continue                     # non MESURABLE -- pas un jugement sur le futur
            out.append(c)                    # ...et on accepte, quel que soit ce futur
        return out

    v = selection_invariante_au_futur(honnete_mais_a_besoin_d_un_futur, CANDIDATS, MARKS)
    assert v.lookahead is False, "faux positif : ce selecteur ne LIT pas le futur, il le SUBIT"
    assert v.survivance > 0, "l'effacement du futur devrait bien retirer des candidats"


def test_un_selecteur_HONNETE_passe():
    """Il ne lit que des champs du candidat. Le futur peut brûler : sa decision ne bouge pas."""

    def honnete(candidats, marks):
        return [c for c in candidats if float(c["current_mid"]) > 60.0]

    v = selection_invariante_au_futur(honnete, CANDIDATS, MARKS)
    assert v.propre is True
    assert v.ecarts == {}
    assert v.acceptes_reel == 2


def test_un_selecteur_qui_lit_le_PASSE_passe_aussi():
    """Lire le passe n'est PAS du lookahead. Le detecteur ne doit pas crier au loup."""

    def passe_seulement(candidats, marks):
        out = []
        for c in candidats:
            avant = [m for (t, m) in marks.get(c["coin"], []) if t <= float(c["recorded_at"])]
            if avant and avant[-1] > 60.0:
                out.append(c)
        return out

    v = selection_invariante_au_futur(passe_seulement, CANDIDATS, MARKS)
    assert v.propre is True, "lire le PASSE a ete pris pour du lookahead : faux positif"


# ====================================================== LES TORTURES


def test_la_torture_detruit_le_FUTUR_et_PRESERVE_le_passe():
    """Si la torture cassait aussi le passe, tout selecteur honnete serait accuse a tort."""
    for mode in (FUTUR_EFFACE, FUTUR_BROUILLE, FUTUR_INVERSE):
        faux = torturer_les_marks(MARKS, coupure_ts=1000.0, mode=mode)
        passe_vrai = [(t, m) for (t, m) in MARKS["BTC"] if t <= 1000.0]
        passe_faux = [(t, m) for (t, m) in faux["BTC"] if t <= 1000.0]
        assert passe_faux == passe_vrai, f"{mode} a abime le PASSE"


def test_FUTUR_EFFACE_supprime_bien_les_marks_posterieurs():
    faux = torturer_les_marks(MARKS, coupure_ts=1000.0, mode=FUTUR_EFFACE)
    assert all(t <= 1000.0 for (t, _m) in faux["BTC"])


def test_FUTUR_INVERSE_garde_les_horodatages_et_retourne_les_prix():
    faux = torturer_les_marks(MARKS, coupure_ts=1000.0, mode=FUTUR_INVERSE)
    ts_vrais = [t for (t, _m) in MARKS["BTC"] if t > 1000.0]
    ts_faux = [t for (t, _m) in faux["BTC"] if t > 1000.0]
    assert ts_faux == ts_vrais, "l'horodatage doit etre intact : seul le PRIX change"
    prix_faux = [m for (t, m) in faux["BTC"] if t > 1000.0]
    prix_vrais = [m for (t, m) in MARKS["BTC"] if t > 1000.0]
    assert prix_faux == prix_vrais[::-1]


def test_la_coupure_par_defaut_est_AVANT_le_premier_signal():
    """Sinon on ne detruirait le futur que d'une PARTIE des candidats -- et on se rassurerait
    a tort sur les autres."""
    vus: list[float] = []

    def espion(candidats, marks):
        vus.append(min(len(v) for v in marks.values()))
        return []

    selection_invariante_au_futur(espion, CANDIDATS, MARKS)
    # 1er appel = futur reel ; les suivants = tortures. Avec coupure = 1000 (min recorded_at),
    # FUTUR_EFFACE doit avoir strictement moins de marks que le reel.
    assert vus[0] > vus[1] or vus[0] > vus[2] or vus[0] > vus[3]


def test_aucun_candidat_est_propre_par_defaut_pas_par_accident():
    v = selection_invariante_au_futur(lambda c, m: [], [], {})
    assert v.propre is True
    assert v.raison == "AUCUN_CANDIDAT"


# ====================================================== LE VRAI MOTEUR DE RECHERCHE


def test_la_VRAIE_selection_de_la_recherche_est_INVARIANTE_au_futur():
    """LE test qui compte. On prend `_eval_pairs` -- le coeur reel de la recherche 150 M --
    et on lui detruit le futur. Sa selection ne doit pas bouger d'un candidat.

    Si ce test echoue, TOUS les resultats de recherche sont a jeter.
    """
    from hl_observer.backtesting.scenario_grid import generate
    from hl_observer.backtesting.scenario_search import _config_for, _eval_pairs

    sc = next(iter(generate()))
    cfg = _config_for(sc)

    def selectionner(candidats, marks):
        out = []
        for c in candidats:
            # min_edge=0 : on NEUTRALISE les filtres de qualite pour isoler la seule question
            # qui nous interesse ici -- la dependance au FUTUR. Un filtre d'edge actif ferait
            # tomber tous les candidats de test (ils n'ont pas de `edge_remaining_bps`) et le
            # test passerait sur un ensemble VIDE : il ne prouverait rien.
            if list(_eval_pairs([c], marks, cfg, float(sc.horizon_min),
                                0.0, float(sc.cost_bps), 500.0,
                                0.0, 0.0, 1, 0.0, 0.0, "both")):
                out.append(c)
        return out

    v = selection_invariante_au_futur(selectionner, CANDIDATS, MARKS)
    assert v.acceptes_reel > 0, (
        "aucun candidat accepte : le test tournerait a VIDE et ne prouverait rien"
    )

    # 1) AUCUN LOOKAHEAD. Brouiller ou INVERSER le futur ne doit rien changer.
    assert v.lookahead is False, (
        "la selection de la recherche CHANGE quand le futur est brouille ou inverse : FUITE. "
        f"Tous les resultats de recherche seraient a jeter. ecarts={v.ecarts} ex={v.exemples}"
    )

    # 2) Mais la SURVIVANCE existe, et on la documente au lieu de la cacher : sans mark futur,
    #    `simulate_exit_on_path` rend None -- le trade n'est pas mesurable. Si rien ne changeait
    #    ici, ce serait BIEN PIRE : ca voudrait dire qu'il INVENTE un prix de sortie.
    assert v.survivance > 0, (
        "effacer le futur ne change RIEN a la selection : simulate_exit_on_path inventerait "
        "donc un prix de sortie quand le carnet de marks s'arrete. C'est un bug plus grave."
    )
