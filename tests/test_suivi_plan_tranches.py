"""LE SUIVI DU COFFRE MONTRE LE DÉCOUPAGE EN TRANCHES.

L'opérateur regardait son écran de suivi pendant une certification — progression, fichiers, débit,
ETA — et a dit : « c'est dommage, on voit pas le découpage en tranches ». Ma première intégration
affichait le plan dans la console du *certificateur*, qui n'est pas l'écran qu'il regarde.

Le plan écrit par le certificateur est donc relu à chaque rafraîchissement et rendu sous la
progression. Ces tests verrouillent ce qui compte : que `rendre` reste **pure**, qu'un plan absent
ou illisible ne casse rien, et que la **borne haute** soit dite à l'écran.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "tools" / "suivi_coffre.py"
_spec = importlib.util.spec_from_file_location("suivi_coffre_plan", _MOD)
SC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SC)


def _plan(tranches=3, heures=136.0, continu=True, borne="HAUTE", fills=13_503_314):
    return {
        "schema": "hypersmart.plan_tranches_coffre.v1",
        "tranches": [[i, i + 1] for i in range(tranches)],
        "couverture": {"continue": continu, "etendue_ms": int(heures * 3_600_000)},
        "borne": borne,
        "mesure": {"lignes": fills},
    }


def _etat():
    return {"stage": "CERTIFICATION", "pct": 56.5, "i": 101, "n": 491,
            "updated_ms": time.time() * 1000, "octets_faits": 7.4e9, "octets_total": 13.0e9,
            "debit_mo_s": 14.0, "eta_s": 404}


# ───────────────────────── ce que l'écran montre ─────────────────────────

def test_le_plan_apparait_SOUS_la_progression():
    lignes = SC.rendre(_etat(), maintenant_ms=time.time() * 1000, plan=_plan(tranches=32))
    texte = "\n".join(lignes)
    assert "Plan labo : 32 tranche(s) au plus" in texte
    assert "136 h" in texte and "continu" in texte
    # la progression reste la première information
    assert texte.index("56.5%") < texte.index("Plan labo")


def test_la_BORNE_HAUTE_est_dite_a_l_ecran():
    """Annoncer « 32 tranches » sans « au plus » ferait chercher un défaut quand il en fera 19."""
    texte = "\n".join(SC.rendre(_etat(), maintenant_ms=time.time() * 1000, plan=_plan()))
    assert "au plus" in texte
    assert "doublons et non-causaux seront ecartes" in texte


def test_un_plan_SANS_borne_haute_n_annonce_pas_au_plus():
    texte = "\n".join(SC.rendre(_etat(), maintenant_ms=time.time() * 1000,
                                plan=_plan(borne="EXACTE")))
    assert "au plus" not in texte and "Plan labo : 3 tranche(s)" in texte


def test_les_fills_de_la_fenetre_sont_affiches_LISIBLEMENT():
    texte = "\n".join(SC.rendre(_etat(), maintenant_ms=time.time() * 1000, plan=_plan()))
    assert "13 503 314 fills" in texte, "séparateurs d'espace, pas de virgules anglaises"


def test_une_couverture_DISCONTINUE_est_signalee():
    """Un trou entre tranches doit sauter aux yeux, pas se cacher derrière un mot neutre."""
    texte = "\n".join(SC.rendre(_etat(), maintenant_ms=time.time() * 1000,
                                plan=_plan(continu=False)))
    assert "DISCONTINU" in texte


# ───────────────────── ce qui ne doit RIEN casser ─────────────────────

def test_SANS_plan_l_ecran_le_dit_et_continue():
    lignes = SC.rendre(_etat(), maintenant_ms=time.time() * 1000, plan=None)
    texte = "\n".join(lignes)
    assert "aucun" in texte and "prochaine certification" in texte
    assert "56.5%" in texte, "la progression reste affichée"


def test_un_plan_ILLISIBLE_ne_fait_pas_planter_l_ecran():
    """Le certificateur écrit ce fichier pendant qu'on le lit : un JSON tronqué arrive."""
    texte = "\n".join(SC.rendre(_etat(), maintenant_ms=time.time() * 1000, plan={"tranches": "?"}))
    assert "illisible" in texte and "certification reste valide" in texte


def test_l_ecran_D_ATTENTE_montre_aussi_le_plan():
    """C'est entre deux certifications qu'on veut le consulter."""
    texte = "\n".join(SC.rendre(None, maintenant_ms=time.time() * 1000, plan=_plan(tranches=19)))
    assert "En attente d'une certification" in texte
    assert "Plan labo : 19 tranche(s)" in texte


def test_rendre_reste_une_fonction_PURE():
    """Elle ne doit lire aucun fichier : c'est ce qui la rend testable sans disque."""
    import inspect

    source = inspect.getsource(SC.rendre)
    assert "open(" not in source and "read_text" not in source
    assert "lire_le_plan" not in source, "le plan est PASSÉ, jamais lu ici"


# ───────────────────── la lecture du plan, à part ─────────────────────

def test_lire_le_plan_rend_None_si_le_fichier_est_ABSENT(tmp_path):
    assert SC.lire_le_plan(tmp_path) is None


def test_lire_le_plan_rend_None_si_le_JSON_est_TRONQUE(tmp_path):
    chemin = tmp_path.joinpath(*SC.CHEMIN_PLAN)
    chemin.parent.mkdir(parents=True)
    chemin.write_text('{"tranches": [[1, 2', encoding="utf-8")
    assert SC.lire_le_plan(tmp_path) is None


def test_lire_le_plan_rend_le_plan_quand_il_est_valide(tmp_path):
    chemin = tmp_path.joinpath(*SC.CHEMIN_PLAN)
    chemin.parent.mkdir(parents=True)
    chemin.write_text(json.dumps(_plan(tranches=7)), encoding="utf-8")
    plan = SC.lire_le_plan(tmp_path)
    assert plan is not None and len(plan["tranches"]) == 7


def test_la_boucle_RELIT_le_plan_a_chaque_cycle():
    """Sans cela, il faudrait quitter et relancer le suivi pour voir le plan apparaître."""
    import inspect

    source = inspect.getsource(SC.boucle)
    assert "lire_le_plan(racine)" in source
    assert "plan=plan" in source
