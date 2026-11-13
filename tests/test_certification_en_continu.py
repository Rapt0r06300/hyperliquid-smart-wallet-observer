"""Certifier MEME si la campagne est fermee brutalement (demande de Florent, 12/11/2026).

Avant : la certification n'avait lieu qu'a l'ARRET PROPRE (touche q) ou au DEMARRAGE suivant. Une
campagne de six jours fermee par accident au jour cinq laissait cinq jours de donnees NON certifiees
— et le labo ne lit QUE le coffre certifie, donc ces cinq jours lui restaient invisibles tant que
personne ne relancait. (Cas reel du soir : Florent a ferme la fenetre par megarde.)

Le mode boucle appelle `main()` — il ne REDUIT ni ne DUPLIQUE la logique de certification, qui reste
la seule autorite. Ces tests verrouillent surtout la propriete qui compte pour une campagne longue :
**une passe en echec n'arrete pas les cinq jours suivants**.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))


def _module():
    spec = importlib.util.spec_from_file_location(
        "sceller_coffre", RACINE / "tools" / "sceller_coffre_local.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _compteur(module, codes=None):
    """Remplace `main` par un espion ; `codes` donne le code rendu a chaque passe."""
    appels: list[list[str]] = []
    suite = list(codes or [])

    def faux_main(argv):
        appels.append(list(argv))
        return suite.pop(0) if suite else 0

    module.main = faux_main
    return appels


def test_la_boucle_APPELLE_main_et_ne_duplique_rien():
    m = _module()
    appels = _compteur(m)
    m.boucler(["--root", "."], 60.0, limite_passes=3, dormir=lambda s: None, horloge=lambda: 0.0)
    assert len(appels) == 3
    assert all(a == ["--root", "."] for a in appels)


def test_une_passe_en_ECHEC_n_arrete_PAS_la_boucle():
    """LE point : une certification qui echoue a 3 h du matin ne doit pas condamner la suite."""
    m = _module()
    appels: list[int] = []

    def main_qui_plante(argv):
        appels.append(1)
        if len(appels) == 1:
            raise RuntimeError("disque occupe")
        return 0

    m.main = main_qui_plante
    code = m.boucler(["--root", "."], 60.0, limite_passes=3, dormir=lambda s: None,
                     horloge=lambda: 0.0)
    assert len(appels) == 3
    assert code == 0


def test_un_code_de_retour_non_nul_n_arrete_pas_non_plus():
    m = _module()
    _compteur(m, codes=[2, 0, 0])
    code = m.boucler(["--root", "."], 60.0, limite_passes=3, dormir=lambda s: None,
                     horloge=lambda: 0.0)
    assert code == 0


def test_elle_ATTEND_bien_entre_deux_passes():
    m = _module()
    _compteur(m)
    attentes: list[float] = []
    m.boucler(["--root", "."], 1800.0, limite_passes=3, dormir=attentes.append,
              horloge=lambda: 0.0)
    assert attentes == [1800.0, 1800.0]        # pas d'attente apres la derniere passe


def test_Ctrl_C_sort_IMMEDIATEMENT():
    """Regle du projet : Ctrl+C ne doit jamais etre avale (deja corrige sur les collecteurs)."""
    m = _module()

    def main_interrompu(argv):
        raise KeyboardInterrupt

    m.main = main_interrompu
    with pytest.raises(KeyboardInterrupt):
        m.boucler(["--root", "."], 60.0, dormir=lambda s: None, horloge=lambda: 0.0)


# ------------------------------------------------------------------ le point d'entree

def test_sans_boucle_le_comportement_d_origine_est_INTACT():
    """Non-regression : tous les appels existants (lanceur, .cmd, tests) ne changent pas."""
    m = _module()
    appels = _compteur(m)
    m._point_d_entree(["--root", ".", "--tout"])
    assert appels == [["--root", ".", "--tout"]]


def test_l_option_boucle_est_RETIREE_avant_d_appeler_main():
    """Sinon `main` recevrait un argument qu'il ne connait pas et planterait a chaque passe."""
    m = _module()
    appels = _compteur(m)
    m.boucler = lambda argv, intervalle, **k: appels.append(list(argv)) or 0
    m._point_d_entree(["--root", ".", "--boucle-s", "1800"])
    assert appels == [["--root", "."]]


def test_la_forme_avec_egal_marche_aussi():
    m = _module()
    appels = _compteur(m)
    m.boucler = lambda argv, intervalle, **k: appels.append(list(argv)) or 0
    m._point_d_entree(["--boucle-s=900", "--root", "."])
    assert appels == [["--root", "."]]


def test_le_certificateur_est_au_registre_avec_une_cadence_sure():
    """Il doit tourner TOUT SEUL pendant les campagnes futures, pas dependre d'un geste humain."""
    from hl_observer.ops import collecteur_registry as R
    c = next((x for x in R.REGISTRE if x["nom"] == "coffre-certificateur"), None)
    assert c is not None, "absent du registre"
    assert c["limite_minutes"] * 60.0 > c["intervalle_s"] * 1.5      # garde anti-relance
    assert "coffre-certificateur" in R.COLLECTEURS_HARVEST
