"""AlinaSync ne doit JAMAIS se figer — incident mesure du 13/11/2026.

CE QUI S'EST PASSE. Deux `git merge` lances par la chaine de synchronisation se sont bloques
a **0 % CPU et 0 operation disque**, apres avoir pourtant consomme 848 s de CPU utile, en
retenant 1,7 Go chacun. Il a fallu les tuer a la main. Cause : `subprocess.run` sans `stdin`
herite de l'entree du parent ; quand le parent meurt — le systeme a tue le notre deux fois pour
pression memoire — git reste bloque a lire une entree qui ne viendra jamais. Et sans `timeout`,
personne ne vient jamais le reveiller.

Trois durcissements sont verrouilles ici :

1. **entree fermee** : git ne peut plus attendre un parent mort ;
2. **delai maximal** : un outil qui attend sans fin n'est pas robuste, il prefere mourir en le
   disant — et son message doit NOMMER la cause et les remedes, pas se contenter de « timeout » ;
3. **`--no-optional-locks` en lecture** : plusieurs outils travaillent en parallele sur ce depot
   et se bloquaient mutuellement sur `.git/index.lock`, parfois perime un quart d'heure durant.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))


def _module():
    spec = importlib.util.spec_from_file_location(
        "sync_clone", RACINE / "tools" / "sync_complete_clone.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _espionner(module):
    """Remplace subprocess.run et retourne la liste des appels observes."""
    vus: list[dict] = []

    def faux_run(cmd, **kw):
        vus.append({"cmd": list(cmd), **kw})

        class Resultat:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Resultat()

    module.subprocess.run = faux_run
    return vus


# ------------------------------------------------------------------ entree fermee

def test_git_ne_peut_JAMAIS_attendre_une_entree():
    """LE correctif du blocage : sans cela, git herite du stdin d'un parent qui peut mourir."""
    m = _module()
    vus = _espionner(m)
    m._git(Path("."), "rev-parse", "HEAD")
    m._git(Path("."), "merge", "--ff-only", "x")
    assert vus, "aucun appel observe"
    for appel in vus:
        assert appel.get("stdin") is subprocess.DEVNULL, appel["cmd"]


# ------------------------------------------------------------------ delai maximal

def test_toute_commande_porte_un_delai():
    m = _module()
    vus = _espionner(m)
    m._git(Path("."), "rev-parse", "HEAD")
    m._git(Path("."), "fetch", "--no-tags", "origin", "main")
    for appel in vus:
        assert appel.get("timeout"), f"aucun delai sur {appel['cmd']}"
        assert appel["timeout"] > 0


def test_le_reseau_a_un_delai_PLUS_LARGE_que_le_local():
    """Un fetch de plusieurs Go est lent par nature : lui imposer le delai local le tuerait."""
    m = _module()
    vus = _espionner(m)
    m._git(Path("."), "rev-parse", "HEAD")
    m._git(Path("."), "fetch", "origin", "main")
    local, reseau = vus[0]["timeout"], vus[1]["timeout"]
    assert reseau > local


def test_un_depassement_leve_une_erreur_au_lieu_de_se_figer():
    m = _module()

    def run_qui_traine(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1.0))

    m.subprocess.run = run_qui_traine
    with pytest.raises(m.SyncError) as capture:
        m._git(Path("."), "merge", "--ff-only", "x")
    message = str(capture.value)
    # Un message doit faire AGIR : nommer la cause mesuree ET les remedes.
    assert "depasse" in message
    assert "sparse-checkout" in message
    assert "ECRIT EN CONTINU" in message


# ------------------------------------------------------------------ verrous

def test_les_lectures_n_entrent_PAS_en_conflit_sur_le_verrou():
    m = _module()
    vus = _espionner(m)
    for lecture in ("rev-parse", "rev-list", "ls-files", "config"):
        m._git(Path("."), lecture, "HEAD")
    for appel in vus:
        assert "--no-optional-locks" in appel["cmd"], appel["cmd"]


def test_une_ECRITURE_prend_bien_le_verrou():
    """L'inverse compte autant : une fusion DOIT verrouiller, sinon elle corromprait l'index."""
    m = _module()
    vus = _espionner(m)
    m._git(Path("."), "merge", "--ff-only", "x")
    assert "--no-optional-locks" not in vus[0]["cmd"]


# ------------------------------------------------------------------ le raccourci de vitesse

def test_CANARI_la_fusion_est_SAUTEE_quand_il_n_y_a_rien_a_fusionner():
    """Mesure : 0,206 s de verification contre plus de 30 min de fusion inutile."""
    import ast
    import inspect
    import textwrap

    m = _module()
    source = textwrap.dedent(inspect.getsource(m.synchronize_main))
    arbre = ast.parse(source)
    appels_merge = [n for n in ast.walk(arbre)
                    if isinstance(n, ast.Call) and any(
                        isinstance(a, ast.Constant) and a.value == "merge" for a in n.args)]
    assert appels_merge, "plus aucun merge : le raccourci est alle trop loin"
    # Le merge doit etre SOUS une condition, jamais au premier niveau de la fonction.
    corps_direct = [n for n in arbre.body[0].body if isinstance(n, ast.Expr)]
    for noeud in corps_direct:
        if isinstance(noeud.value, ast.Call):
            assert not any(isinstance(a, ast.Constant) and a.value == "merge"
                           for a in noeud.value.args), "merge appele inconditionnellement"
