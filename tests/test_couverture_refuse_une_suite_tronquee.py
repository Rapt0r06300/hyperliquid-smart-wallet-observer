"""#599 — UN INSTRUMENT DOIT SAVOIR DIRE « JE N'AI PAS PU MESURER ».

L'HISTOIRE
----------
Le 2026-07-13 a 14:07, `tools/couverture_de_lignes.py` a publie **83,83 %** de couverture. Le
chiffre etait FAUX : la suite avait ete interrompue a ~70 % par le Ctrl-C fantome (#600), et
coverage.py avait calcule son pourcentage sur une suite **amputee de 1 278 tests**.

La consequence n'etait pas « un chiffre un peu bas ». Elle etait bien pire : **six modules
apparaissaient a 0,00 %** -- accuses d'etre du code mort, alors que leurs tests n'avaient
simplement jamais eu lieu. Une mesure fausse ne se contente pas de se tromper : **elle accuse.**

Et l'outil, lui, n'a rien vu. Il a lu `coverage.json`, trouve un nombre, et l'a publie.

CE QUE CE FICHIER VERROUILLE
----------------------------
Deux fonctions, deux questions :
  * `_run_interrompu(sortie)` -> la suite s'est-elle arretee en cours de route ?
  * `_tests_executes(sortie)` -> combien de tests ont REELLEMENT tourne ?

Si la premiere repond « oui », l'outil doit **refuser de publier**. Un blanc dans la mesure doit
se VOIR ; il ne doit jamais se deviner.

Aucun ordre reel.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

from couverture_de_lignes import _run_interrompu, _tests_executes  # noqa: E402


# ============================================================ 1. DETECTER L'INTERRUPTION


def test_une_suite_INTERROMPUE_est_reconnue_comme_telle():
    """La sortie REELLE du 13/07 (Ctrl-C fantome). Elle DOIT etre rejetee."""
    reel = (
        "........................................ [ 70%]\n"
        "!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!\n"
        "2242 passed in 178.30s\n"
    )
    assert _run_interrompu(reel), (
        "l'outil a pris une suite Ctrl-C-ee pour un run complet -- c'est EXACTEMENT le bug du "
        "13/07 : 83,83 %% publies sur une suite amputee de 1 278 tests, et 6 modules accuses a tort"
    )


def test_une_suite_arretee_par_maxfail_est_aussi_une_suite_TRONQUEE():
    assert _run_interrompu("!!!! stopping after 1 failures !!!!\n3 passed, 1 failed\n")
    assert _run_interrompu("!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!\n")


def test_une_suite_COMPLETE_passe_sans_alarme():
    """🚩 Un garde-fou qui alarme TOUJOURS ne garde rien : il apprend juste a etre ignore.

    La sortie reelle d'un run sain (13/07, apres correctif #600) doit passer SANS declencher.
    """
    sain = "........................ [100%]\n3520 passed, 22403 warnings in 244.44s (0:04:04)\n"
    assert _run_interrompu(sain) is None, "faux positif : un run COMPLET a ete pris pour tronque"


def test_une_suite_avec_des_ROUGES_n_est_PAS_une_suite_tronquee():
    """Distinction essentielle : « des tests echouent » n'est pas « la suite s'est arretee ».

    Les confondre ferait taire l'outil precisement les jours ou l'on a le plus besoin de lui.
    """
    rouge = "5 failed, 3512 passed, 22403 warnings in 238.20s\n"
    assert _run_interrompu(rouge) is None
    assert _tests_executes(rouge) == 3517


# ============================================================ 2. COMPTER LES TESTS


def test_le_nombre_de_tests_est_LU_dans_la_sortie_pas_devine():
    assert _tests_executes("3520 passed, 22403 warnings in 244.44s") == 3520
    assert _tests_executes("2242 passed in 178.30s") == 2242
    assert _tests_executes("1 failed, 14 passed in 2.96s") == 15
    assert _tests_executes("") == 0


def test_zero_test_compte_veut_dire_MESURE_IMPOSSIBLE_pas_zero_couverture():
    """Si on ne sait pas COMBIEN de tests ont tourne, on ne sait pas ce que vaut le pourcentage.

    `main()` traite ce cas comme un refus de publication (return 2), jamais comme un « 0 % ».
    """
    assert _tests_executes("no tests ran in 0.01s") == 0
