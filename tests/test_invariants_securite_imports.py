"""#2/#18 — INVARIANTS : aucun module n'ouvre une porte d'exécution, et pas de cycle d'imports
dans les paquets de décision. Cliquets : si quelqu'un ajoute une lib d'ordre ou un cycle, ça casse."""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hl_observer"
PAQUETS_DECISION = ("funding", "gating", "ops", "market", "pipeline", "edge")

# APPELS interdits (vraie capacite d'execution). On detecte des APPELS via AST, PAS des mots dans
# un commentaire : un module qui ECRIT "n'appelle jamais /exchange" est innocent.
APPELS_INTERDITS = {"place_order", "create_order", "submit_order", "sign_l1_action", "sign_action"}
# Le stub live_executor_disabled DEFINIT place_order pour le REFUSER : c'est le garde, pas la faute.
FICHIERS_EXEMPTS = {"execution/live_executor_disabled.py"}
EXEMPTS = ("test", "audit", "safety", "tombstone")   # audits/docs peuvent NOMMER ces fonctions


def _nom_appel(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def test_aucun_module_n_APPELLE_une_fonction_d_execution():
    """#2 : aucun APPEL reel a une fonction qui placerait un ordre. Les mentions en doc sont permises
    (le projet en parle beaucoup) ; seul un APPEL serait une vraie porte."""
    coupables = []
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(SRC)).replace("\\", "/")
        if rel in FICHIERS_EXEMPTS or any(e in rel.lower() for e in EXEMPTS):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _nom_appel(n) in APPELS_INTERDITS:
                coupables.append((rel, _nom_appel(n), getattr(n, "lineno", 0)))
    assert not coupables, "APPEL d'execution reel detecte : %s" % coupables[:3]


def test_pas_de_cycle_d_imports_dans_les_paquets_de_decision():
    graphe = defaultdict(set)
    for paquet in PAQUETS_DECISION:
        d = SRC / paquet
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            mod = "hl_observer.%s.%s" % (paquet, p.stem)
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("hl_observer."):
                    if any(("hl_observer.%s." % q) in n.module for q in PAQUETS_DECISION):
                        graphe[mod].add(n.module)

    etat: dict = {}

    def cycle(n):
        if etat.get(n) == 1:
            return True
        if etat.get(n) == 2:
            return False
        etat[n] = 1
        for v in graphe.get(n, ()):
            if cycle(v):
                return True
        etat[n] = 2
        return False

    boucles = [n for n in list(graphe) if cycle(n)]
    assert not boucles, "cycle d'imports detecte : %s" % boucles[:3]
