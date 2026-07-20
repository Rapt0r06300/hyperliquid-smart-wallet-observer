"""BOUCLE /GOAL DU REPLAY — les trois arrêts vérifiables, la porte souveraine, l'état qui survit.

Le test central est le n°2 : un rapport qui SE DÉCLARE gagnant ne promeut rien si la PORTE
dit non. C'est l'avertissement de l'article (« a loop without a real stopping condition
fails quietly ») transformé en cliquet.
"""
from __future__ import annotations

import json

from hl_observer.backtesting.boucle_objectif_replay import (
    STATUT_BUDGET_EPUISE, STATUT_ESPACE_EPUISE, STATUT_PROMU, boucle_objectif, cle_config,
)

CONFIGS = [{"sl": 40, "tp": 70}, {"sl": 30, "tp": 90}, {"sl": 50, "tp": 60}]


def test_1_la_boucle_s_arrete_a_la_PREMIERE_config_promue():
    vus = []
    def evaluer(c):
        vus.append(c)
        return {"score": c["tp"]}
    resultat = boucle_objectif(CONFIGS, evaluer, porte=lambda r: r["score"] >= 90)
    assert resultat["statut"] == STATUT_PROMU
    assert resultat["gagnant"] == {"sl": 30, "tp": 90}
    assert len(vus) == 2, "on s'arrete DES que la porte passe — pas d'essai gaspille"


def test_2_un_rapport_qui_SE_DECLARE_gagnant_ne_promeut_RIEN():
    """LE CLIQUET DE L'ARTICLE : « jamais l'agent dit que c'est fini ». L'evaluateur peut
    ecrire verdict=PROMU dans son propre rapport — seule la PORTE (separee) decide."""
    resultat = boucle_objectif(
        CONFIGS, lambda c: {"verdict": "PROMU", "auto_congratulation": True},
        porte=lambda r: False)
    assert resultat["statut"] == STATUT_ESPACE_EPUISE
    assert resultat["gagnant"] is None
    assert all(e["verdict"] == "REJETE" for e in resultat["essais"])


def test_3_espace_epuise_est_un_verdict_HONNETE():
    resultat = boucle_objectif(CONFIGS, lambda c: {"s": 0}, porte=lambda r: False)
    assert resultat["statut"] == STATUT_ESPACE_EPUISE and resultat["n_essais_total"] == 3


def test_4_le_budget_d_essais_borne_le_run():
    resultat = boucle_objectif(CONFIGS, lambda c: {"s": 0}, porte=lambda r: False, max_essais=2)
    assert resultat["statut"] == STATUT_BUDGET_EPUISE and resultat["n_essais_total"] == 2


def test_5_l_etat_survit_et_la_reprise_ne_repaye_PAS(tmp_path):
    """Ctrl-C au milieu -> l'etat a chaque essai ; le run suivant saute les configs jugees."""
    etat = tmp_path / "etat.json"
    boucle_objectif(CONFIGS, lambda c: {"s": 0}, porte=lambda r: False,
                    etat_path=etat, max_essais=2)
    assert len(json.loads(etat.read_text(encoding="utf-8"))["essais"]) == 2

    vus = []
    def evaluer(c):
        vus.append(c)
        return {"s": 0}
    r2 = boucle_objectif(CONFIGS, evaluer, porte=lambda r: False, etat_path=etat)
    assert vus == [CONFIGS[2]], "seule la 3e config restait a juger"
    assert r2["statut"] == STATUT_ESPACE_EPUISE and r2["n_essais_total"] == 3


def test_6_une_evaluation_qui_EXPLOSE_est_notee_et_la_boucle_continue():
    def evaluer(c):
        if c["sl"] == 30:
            raise RuntimeError("donnees corrompues")
        return {"score": c["tp"]}
    r = boucle_objectif(CONFIGS, evaluer, porte=lambda r: r.get("score", 0) >= 60)
    # config 1 (tp=70) passe la porte AVANT que la 2 n'explose -> PROMU au 1er essai
    assert r["statut"] == STATUT_PROMU and r["n_essais_total"] == 1
    # et si la porte est plus dure : l'erreur n'arrete pas la recherche
    r2 = boucle_objectif(CONFIGS, evaluer, porte=lambda r: False)
    assert [e["verdict"] for e in r2["essais"]] == ["REJETE", "ERREUR", "REJETE"]


def test_7_la_cle_de_config_est_STABLE_et_discriminante():
    assert cle_config({"a": 1, "b": 2}) == cle_config({"b": 2, "a": 1})
    assert cle_config({"a": 1}) != cle_config({"a": 2})
