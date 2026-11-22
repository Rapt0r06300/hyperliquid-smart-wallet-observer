"""ON NE TUE PAS UN PID : on tue un processus dont on a VERIFIE l'identite.

CE QUE CES TESTS INTERDISENT, et pourquoi. `LANCER_COLLECTEURS_COPY_VAULT.cmd` arretait les
collecteurs de deux facons, toutes deux dangereuses :

```
taskkill /PID %%P /T /F                        <- PID lu dans un .pid, aucune verification
taskkill /FI "WINDOWTITLE eq ALINA-POLL-*"     <- un TITRE DE FENETRE n'est pas une identite
```

Windows **recycle les PID**. Un `.pid` perime pointe donc, un jour, vers un processus
innocent -- et `/T /F` emporte tout son arbre. Le 22/11/2026, pendant cette mission, douze
`python.exe` tournaient sur ce PC (les ouvriers d'une suite de tests) : n'importe lequel
pouvait porter un PID recycle. Le titre de fenetre est pire encore : il n'appartient a
personne.

LA REGLE POSEE ICI : un processus n'est arrete que si sa ligne de commande reference la
RACINE du projet ET un marqueur de collecteur, et qu'il n'est pas dans la liste des exclus
(ecran, scelleur, sync, labo). Tout ce qui ne s'identifie pas est REFUSE **et dit**, jamais
tue en silence et jamais ignore en silence.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import collecteurs_balayage as B  # noqa: E402

PROJET = "C:/Users/flo/Desktop/Projet invest"


def _proc(pid, cmd, owner="flo"):
    return {"pid": pid, "cmdline": cmd, "owner": owner}


# ----------------------------------------------------- identite d'un PID de fichier .pid
def test_un_pid_qui_ne_reference_PAS_le_projet_est_refuse():
    """Le cas du PID recycle : meme nom d'executable, mais ce n'est pas notre processus."""
    processus = [_proc(4242, "C:/Python/python.exe -m pip install quelquechose")]
    verdict = B.identifier_pid(4242, processus=processus, racine=PROJET)
    assert verdict["identifie"] is False
    assert verdict["motif"] == "HORS_PROJET"


def test_un_pid_du_projet_mais_SANS_marqueur_collecteur_est_refuse():
    processus = [_proc(4242, f"{PROJET}/tools/python/python.exe {PROJET}/tools/autre.py")]
    verdict = B.identifier_pid(4242, processus=processus, racine=PROJET)
    assert verdict["identifie"] is False
    assert verdict["motif"] == "PAS_UN_COLLECTEUR"


def test_un_pid_EXCLU_est_refuse_meme_s_il_matche_un_marqueur():
    """L'ecran temps reel porte `collecter_` dans sa ligne : il ne doit pas mourir."""
    ligne = (f"{PROJET}/tools/python/python.exe {PROJET}/tools/affichage_temps_reel.py"
             " --collecter_tout")
    verdict = B.identifier_pid(4242, processus=[_proc(4242, ligne)], racine=PROJET)
    assert verdict["identifie"] is False
    assert verdict["motif"] == "EXCLU"


def test_un_pid_ABSENT_de_la_table_est_refuse_et_NOMME():
    """Un `.pid` perime : le processus n'existe plus. On ne tue pas << au cas ou >>."""
    verdict = B.identifier_pid(4242, processus=[], racine=PROJET)
    assert verdict["identifie"] is False
    assert verdict["motif"] == "INTROUVABLE"


def test_un_vrai_collecteur_du_projet_est_identifie():
    ligne = (f"{PROJET}/tools/python/python.exe {PROJET}/tools/run_bounded_collector.py"
             " --famille fills")
    verdict = B.identifier_pid(777, processus=[_proc(777, ligne)], racine=PROJET)
    assert verdict["identifie"] is True
    assert verdict["motif"] == "IDENTIFIE"
    assert "run_bounded_collector" in verdict["marqueurs"]


def test_le_PROPRIETAIRE_peut_etre_exige():
    """La mission demande de verifier le proprietaire : un collecteur lance par un autre
    compte n'est pas le notre, et le tuer serait une intrusion."""
    ligne = f"{PROJET}/tools/python/python.exe {PROJET}/tools/collecter_bbo.py"
    verdict = B.identifier_pid(777, processus=[_proc(777, ligne, owner="SYSTEM")],
                               racine=PROJET, proprietaire="flo")
    assert verdict["identifie"] is False
    assert verdict["motif"] == "AUTRE_PROPRIETAIRE"
    # Sans exigence de proprietaire, le meme processus s'identifie.
    assert B.identifier_pid(777, processus=[_proc(777, ligne, owner="SYSTEM")],
                            racine=PROJET)["identifie"] is True


def test_un_pid_illisible_est_refuse_sans_lever():
    """Un `.pid` corrompu ne doit ni tuer, ni faire tomber le lanceur."""
    for mauvais in ("", "   ", "abc", "-1", "0", None):
        verdict = B.identifier_pid(mauvais, processus=[], racine=PROJET)
        assert verdict["identifie"] is False
        assert verdict["motif"] == "PID_ILLISIBLE", mauvais


# ----------------------------------------------------- l'arret refuse et DIT
def test_arreter_surement_REFUSE_ce_qu_il_ne_peut_pas_identifier():
    """Un refus se voit : il est compte et motive, jamais avale."""
    vrai = (f"{PROJET}/tools/python/python.exe {PROJET}/tools/run_bounded_collector.py")
    processus = [_proc(777, vrai), _proc(4242, "C:/Python/python.exe -m pip install x")]
    tues: list[int] = []
    bilan = B.arreter_surement([777, 4242, 999], processus=processus, racine=PROJET,
                               tuer=tues.append)
    assert tues == [777], "seul le collecteur identifie doit etre arrete"
    assert bilan["arretes"] == [777]
    motifs = {r["pid"]: r["motif"] for r in bilan["refuses"]}
    assert motifs == {4242: "HORS_PROJET", 999: "INTROUVABLE"}


def test_arreter_surement_n_arrete_JAMAIS_le_process_courant():
    import os
    moi = os.getpid()
    ligne = f"{PROJET}/tools/python/python.exe {PROJET}/tools/collecter_bbo.py"
    tues: list[int] = []
    bilan = B.arreter_surement([moi], processus=[_proc(moi, ligne)], racine=PROJET,
                               tuer=tues.append)
    assert tues == []
    assert bilan["refuses"][0]["motif"] == "PROCESS_COURANT"


def test_une_erreur_d_arret_est_RAPPORTEE_pas_avalee():
    """Si l'arret echoue (droits, course), le lanceur doit le savoir."""
    ligne = f"{PROJET}/tools/python/python.exe {PROJET}/tools/collecter_bbo.py"

    def tuer_qui_echoue(_pid):
        raise PermissionError("WinError 5")

    bilan = B.arreter_surement([777], processus=[_proc(777, ligne)], racine=PROJET,
                               tuer=tuer_qui_echoue)
    assert bilan["arretes"] == []
    assert bilan["echecs"][0]["pid"] == 777
    assert "PermissionError" in bilan["echecs"][0]["erreur"]


# ----------------------------------------------------- le verrou porte une IDENTITE
def test_le_verrou_porte_le_PID_et_la_commande_pas_un_nombre_aleatoire(tmp_path):
    """Le lanceur ecrivait `%RANDOM%%RANDOM%` sous un commentaire disant << PID du cmd
    courant >> : le code contredisait son commentaire et le verrou n'identifiait personne."""
    chemin = tmp_path / "collecteurs.lock"
    B.ecrire_verrou(chemin, pid=4242, commande="LANCER_COLLECTEURS_COPY_VAULT.cmd",
                    horodatage_ms=1_700_000_000_000)
    lu = B.lire_verrou(chemin)
    assert lu["pid"] == 4242
    assert lu["commande"] == "LANCER_COLLECTEURS_COPY_VAULT.cmd"
    assert lu["horodatage_ms"] == 1_700_000_000_000


def test_un_verrou_ILLISIBLE_ne_fait_pas_croire_a_une_campagne(tmp_path):
    """Un verrou corrompu doit dire << je ne sais pas >>, pas << tout va bien >>."""
    chemin = tmp_path / "collecteurs.lock"
    chemin.write_text("3217625412\n", encoding="utf-8")       # l'ancien format aleatoire
    lu = B.lire_verrou(chemin)
    assert lu["pid"] is None
    assert lu["motif"] == "FORMAT_ANCIEN_OU_ILLISIBLE"


def test_un_verrou_ABSENT_se_distingue_d_un_verrou_illisible(tmp_path):
    lu = B.lire_verrou(tmp_path / "jamais_ecrit.lock")
    assert lu["pid"] is None
    assert lu["motif"] == "ABSENT"
