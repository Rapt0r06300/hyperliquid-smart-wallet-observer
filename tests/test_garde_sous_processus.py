"""LE GARDE DOIT VOIR UNE FUITE, LA RÉPARER, ET LAISSER PASSER UN REMPLACEMENT PROPRE.

Voir `tests/garde_sous_processus.py`. Le 17/11/2026, un espion posé par affectation directe sur
`subprocess.run` survivait à son test : la suite complète a rendu 7 échecs sans rapport apparent,
tous passant une fois rejoués seuls. Ces tests verrouillent le garde lui-même — un contrôle qui ne
tire pas quand il le faut, ou qui tire sur un usage correct, serait pire que pas de contrôle.
"""
from __future__ import annotations

import subprocess
import sys

from tests import garde_sous_processus as G


def test_sans_fuite_le_garde_ne_signale_rien():
    assert G.fuites_et_restauration() == []


def test_une_affectation_DIRECTE_est_vue_PUIS_reparee():
    def faux(*_a, **_k):
        raise AssertionError("ce faux ne doit jamais survivre")

    subprocess.run = faux                       # la fuite exacte du 17/11
    try:
        assert G.fuites_et_restauration() == ["run"]
        assert subprocess.run is G.REELS["run"], "la fonction reelle doit etre revenue"
        assert G.fuites_et_restauration() == [], "une seconde passe ne doit plus rien voir"
    finally:
        subprocess.run = G.REELS["run"]


def test_plusieurs_fonctions_remplacees_sont_TOUTES_nommees():
    subprocess.Popen = object                   # type: ignore[assignment,misc]
    subprocess.check_output = object            # type: ignore[assignment]
    try:
        assert G.fuites_et_restauration() == ["Popen", "check_output"]
    finally:
        subprocess.Popen = G.REELS["Popen"]     # type: ignore[misc]
        subprocess.check_output = G.REELS["check_output"]


def test_un_remplacement_par_MONKEYPATCH_est_legitime_pendant_le_test(monkeypatch):
    """Le garde ne s'exécute qu'après la fin des fixtures : monkeypatch aura déjà tout défait."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    assert subprocess.run is not G.REELS["run"], "le remplacement est bien actif pendant le test"


def test_APRES_un_monkeypatch_le_vrai_sous_processus_REPOND():
    """Canari : exécuté après le test précédent, il doit obtenir une VRAIE sortie."""
    assert subprocess.run is G.REELS["run"]
    resultat = subprocess.run([sys.executable, "-c", "print('reel')"], capture_output=True,
                              text=True, check=False, timeout=60)
    assert resultat.returncode == 0 and resultat.stdout.strip() == "reel"


def test_le_fichier_qui_fuyait_ne_laisse_plus_rien(monkeypatch):
    """Le coupable d'origine : son espion doit maintenant être défait par monkeypatch."""
    from tests import test_sync_git_robustesse as coupable

    module = coupable._module()
    vus = coupable._espionner(module, monkeypatch)
    module._git(__import__("pathlib").Path("."), "rev-parse", "HEAD")
    assert vus, "l'espion doit toujours observer les appels pendant le test"
    monkeypatch.undo()
    assert subprocess.run is G.REELS["run"]
    assert G.fuites_et_restauration() == []


def test_le_garde_est_BRANCHE_dans_conftest():
    """Un garde que personne n'appelle ne garde rien."""
    import inspect

    from tests import conftest

    source = inspect.getsource(conftest.pytest_runtest_teardown)
    assert "fuites_et_restauration" in source and "pytest.fail" in source
