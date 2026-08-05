"""AUD-079 — Le verrou d'analyse du laboratoire DOIT être libéré même si le run LÈVE.

`lancer_lab` acquiert `_verrou_analyse` puis exécute ~165 lignes (inventaire, lecture, audit,
recherche, rapport). Avant le correctif, `_verrou_analyse.unlink()` n'était appelé qu'à la
toute fin : une exception EN COURS de run laissait le verrou sur disque → tout run suivant
était bloqué (le reclaim PID-mort ne sauve que l'inter-process, pas le même process/PID vivant).

Ce test (AST, 0 import de hl_observer) échoue si la libération n'est plus dans un `finally`.
0 réseau.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer" / "ops" / "lab_alpha.py"
SRC_TEXT = SRC.read_text(encoding="utf-8")


def _fonction(nom: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(SRC_TEXT)):
        if isinstance(node, ast.FunctionDef) and node.name == nom:
            return node
    raise AssertionError(f"fonction {nom} introuvable dans lab_alpha.py")


def _unlink_verrou_dans_finally(fn: ast.FunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                for sub in ast.walk(stmt):
                    if (isinstance(sub, ast.Attribute) and sub.attr == "unlink"
                            and isinstance(sub.value, ast.Name) and sub.value.id == "_verrou_analyse"):
                        return True
    return False


def test_le_verrou_est_bien_acquis():
    # cohérence : sans acquisition, le test finally n'aurait aucun sens.
    assert "acquerir_verrou_analyse(sortie)" in SRC_TEXT


def test_lancer_lab_libere_le_verrou_dans_un_finally():
    fn = _fonction("lancer_lab")
    assert _unlink_verrou_dans_finally(fn), (
        "lancer_lab doit libérer _verrou_analyse dans un bloc `finally` : sinon une exception "
        "en cours de run FUITE le verrou et bloque tout run suivant (AUD-079)."
    )
