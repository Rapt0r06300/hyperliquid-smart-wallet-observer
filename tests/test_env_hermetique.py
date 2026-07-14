"""UN TEST NE DOIT PAS CHANGER DE VERDICT SELON LA MACHINE QUI LE LANCE (2026-07-12).

LE BUG QUE CE FICHIER VERROUILLE
--------------------------------
`test_ui_simulation_default_profile_allows_bounded_multi_position_mode` attendait `6` -- le
defaut ecrit noir sur blanc dans `src/hl_observer/ui/routes.py` -- et recevait `3`.

Ce `3` n'existait dans AUCUN code de production. Il venait de l'outil d'audit lui-meme :
`tools/audit_report.py` pose `os.environ["HYPERSMART_MAX_OPEN_POSITIONS"] = "3"` pour verifier
qu'un plafond de positions refuse bien la 4e ouverture -- puis lance la suite pytest en
sous-processus, qui heritait de cet environnement.

Le meme code donnait donc DEUX verdicts :
  * `pytest` lance a la main  -> PASS
  * la meme suite sous MEGATEST -> FAIL

**L'outil de verification fabriquait l'echec qu'il rapportait.** C'est la pire panne possible
pour un outil de verite : elle apprend a se mefier des vrais echecs.

LA REGLE, DESORMAIS
-------------------
La suite demarre avec un environnement runtime VIERGE (fixture `env_runtime_neutre`, conftest).
Un test qui veut un calibrage le pose LUI-MEME, dans son corps, sous les yeux du lecteur.

Ces tests sont le cliquet : si quelqu'un retire la fixture, ils tombent immediatement.

Aucun ordre reel.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Volontairement RECOPIE (et non importe de conftest) : ce fichier doit rester lisible seul,
# et un import de `tests.conftest` depend de la facon dont pytest a monte sys.path.
PREFIXES_RUNTIME = ("HYPERSMART_", "HL_")


def test_aucune_variable_de_calibrage_ne_fuit_dans_les_tests():
    """LE CLIQUET. Pendant un test, l'environnement runtime doit etre VIDE.

    Si cette assertion tombe, c'est qu'un processus parent (audit, launcher, shell de Flo)
    impose son calibrage a la suite -- et que les tests ne mesurent plus le code.
    """
    fuites = sorted(k for k in os.environ if k.startswith(PREFIXES_RUNTIME))
    # Ces trois-la sont POSEES par le conftest lui-meme, vers des chemins de TEST :
    #   HL_LOGS_DIR                     -> un tmp_path (les logs reels restent intacts)
    #   HYPERSMART_EDGE_CALIBRATION_PATH -> l'ancienne TEST_FIXTURE d'edge (legacy)
    #   HYPERSMART_EDGE_TABLE_PATH       -> la TEST_FIXTURE de la PORTE UNIQUE (#594)
    # Ce n'est pas une fuite de la MACHINE : c'est un decor, declare dans conftest, sous les yeux
    # du lecteur. La regle que ce test defend -- « un test ne lit pas l'environnement de Flo » --
    # est intacte.
    _DECOR_DU_CONFTEST = {
        "HL_LOGS_DIR",
        "HYPERSMART_EDGE_CALIBRATION_PATH",
        "HYPERSMART_EDGE_TABLE_PATH",
    }
    fuites = [k for k in fuites if k not in _DECOR_DU_CONFTEST]
    assert fuites == [], (
        f"des variables du runtime fuient dans les tests : {fuites}. "
        "Un test qui lit l'environnement de la machine ne prouve rien sur le code."
    )


def test_un_test_qui_pose_sa_variable_la_voit_bien(monkeypatch):
    """La fixture NEUTRALISE l'heritage ; elle n'empeche pas un test de se calibrer."""
    monkeypatch.setenv("HYPERSMART_MAX_OPEN_POSITIONS", "42")
    assert os.environ["HYPERSMART_MAX_OPEN_POSITIONS"] == "42"


def test_la_suite_donne_le_MEME_verdict_avec_un_env_pollue(tmp_path):
    """LA PREUVE PAR L'EXECUTION : on POLLUE volontairement l'environnement comme le faisait
    l'audit, on relance le test qui echouait -- il doit passer quand meme.

    C'est la reproduction exacte du bug, transformee en garde-fou permanent.
    """
    env = dict(os.environ)
    env["HYPERSMART_MAX_OPEN_POSITIONS"] = "3"          # <- la pollution, a l'identique
    env["PYTHONPATH"] = (
        str(RACINE / "src") + os.pathsep + str(RACINE) + os.pathsep + env.get("PYTHONPATH", "")
    )
    env["PYTHONIOENCODING"] = "utf-8"
    # 🔴 #594 : SANS `creationflags`, ce pytest-dans-pytest partage la CONSOLE du parent. Le
    # Ctrl-C que pytest emet en fin de course a alors remonte a la suite COMPLETE et l'a tuee
    # en plein milieu (KeyboardInterrupt, 13/07). C'est le meme bug que `audit_report` (11/07)
    # et `couverture_de_lignes` (13/07) -- 3e recidive, cette fois dans l'angle mort de son
    # propre invariant, qui ne scannait que `tools/`. Il scanne maintenant `tests/` aussi.
    _isole = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_ui_simulation_persistence.py"
         "::test_ui_simulation_default_profile_allows_bounded_multi_position_mode"],
        cwd=str(RACINE), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, creationflags=_isole,
    )
    assert proc.returncode == 0, (
        "le test change de verdict quand l'environnement est pollue : la suite mesure la "
        f"machine, pas le code.\n{proc.stdout[-3000:]}"
    )


def test_l_audit_ne_transmet_plus_son_calibrage_a_pytest():
    """L'autre bout de la corde : `audit_report._run_stream(..., env_propre=True)` pour pytest.

    On verifie la SOURCE plutot que d'executer l'audit entier (6 min) : ce qu'on defend ici,
    c'est que personne ne retire ce garde-fou par inadvertance.
    """
    src = (RACINE / "tools" / "audit_report.py").read_text(encoding="utf-8", errors="replace")
    assert "env_propre" in src, "le garde-fou d'environnement a disparu de l'audit"
    assert src.count("env_propre=True") >= 2, (
        "les DEUX passes pytest de l'audit doivent tourner en environnement propre "
        "(sinon la 2e passe mesurerait la contamination et crierait au test 'flaky')"
    )
