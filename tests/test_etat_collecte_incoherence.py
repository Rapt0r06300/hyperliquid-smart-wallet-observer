"""L'écran d'état ne doit crier « ETAT_INCOHERENT » que sur un état qui se contredit vraiment.

Le 22/11/2026 il le criait sur un état SAIN : 20 PID = 19 collecteurs démarrés + 1 réutilisé
(`userfills-poll`, déjà vivant et repris tel quel). La règle comparait deux longueurs et ne
connaissait pas `reutilises`. Une fausse alerte permanente apprend à ne plus lire les alertes —
et une comparaison de longueurs laisse passer deux listes de même taille aux noms différents.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import etat_collecte_reel as E  # noqa: E402


def _etat(pids, verifies, reutilises=None) -> dict:
    etat = {"pids": {n: 1000 + i for i, n in enumerate(pids)}, "demarres_et_verifies": list(verifies)}
    if reutilises is not None:
        etat["reutilises"] = list(reutilises)
    return etat


def test_un_collecteur_reutilise_n_est_pas_une_incoherence() -> None:
    noms = [f"c{i}" for i in range(19)]
    assert E.incoherence_interne(_etat(noms + ["userfills-poll"], noms, ["userfills-poll"])) is None


def test_un_pid_que_rien_n_a_verifie_ni_repris_est_nomme() -> None:
    alerte = E.incoherence_interne(_etat(["a", "b", "fantome"], ["a", "b"], []))
    assert alerte is not None and alerte.startswith("ETAT_INCOHERENT")
    assert "fantome" in alerte and "ni verifie ni reutilise" in alerte


def test_un_collecteur_annonce_demarre_sans_pid_est_nomme() -> None:
    alerte = E.incoherence_interne(_etat(["a"], ["a", "disparu"], []))
    assert alerte is not None and "disparu" in alerte and "sans PID" in alerte


def test_deux_longueurs_egales_ne_suffisent_pas() -> None:
    # meme nombre de noms des deux cotes, mais pas les MEMES : l'ancienne regle ne voyait rien
    alerte = E.incoherence_interne(_etat(["a", "b"], ["a", "c"], []))
    assert alerte is not None and "b" in alerte and "c" in alerte


def test_un_fichier_sans_ces_champs_n_est_pas_declare_incoherent() -> None:
    assert E.incoherence_interne({}) is None
    assert E.incoherence_interne({"pids": {"a": 1}}) is None
    assert E.incoherence_interne({"pids": ["a"], "demarres_et_verifies": ["a"]}) is None


# ---------------------------------------------------------------- rubans surveilles
def test_chaque_ruban_surveille_est_ecrit_par_un_collecteur_local_du_registre() -> None:
    """Surveiller un fichier que personne n'écrit, c'est une alerte ABSENT pour toujours.

    Le 22/11/2026 deux des quatre rubans surveillés n'avaient aucun collecteur local pour
    producteur (`*_tape.jsonl` au lieu de `*_lane.jsonl`). La source de vérité est le registre
    des flux : ce test y relie chaque ruban, et exige un producteur `tools/collecter_*.py`
    présent sur le disque — pas un téléchargeur, pas un fichier que le labo fabrique.
    """
    if str(RACINE / "src") not in sys.path:
        sys.path.insert(0, str(RACINE / "src"))
    from hl_observer.datasets.couverture_donnees import flux_par_fichier

    registre = flux_par_fichier()
    for relatif in E.RUBANS_SURVEILLES:
        nom = Path(relatif).name
        assert nom in registre, f"{nom} : surveillé mais inconnu du registre des flux — personne ne l'écrit"
        producteur = registre[nom].producteur
        assert Path(producteur).name.startswith("collecter_"), (
            f"{nom} : son producteur est {producteur}, pas un collecteur local")
        assert (RACINE / producteur).is_file(), f"{nom} : producteur {producteur} introuvable"
