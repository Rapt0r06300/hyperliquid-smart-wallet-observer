#!/usr/bin/env python3
"""#166/#169/#240/#241 -- QUI APPELLE VRAIMENT ces 4 modules ? (2026-07-13)

    ml_diagnostics        (SHAP)     -- IDEA-09
    microstructure_extras (Hawkes)   -- IDEA-12
    regime_detection      (Kalman)   -- IDEA-83
    regime_detection      (GARCH)    -- IDEA-84  <- CELUI-LA LIT LE FUTUR (mesure du 13/07)

Par l'**AST**, jamais par grep : un grep compte « sharpe » comme « shap », et il compte les
docstrings comme des appels. On l'a deja paye trois fois aujourd'hui.

TROIS PORTES (lecon de #597 et de T3e) :
  1. un import reel depuis un autre module de `src/` ;
  2. un `-m ...` sur une ligne NON COMMENTEE d'un lanceur (.ps1 / .cmd) ;
  3. un bloc `if __name__ == "__main__":` (point d'entree humain).

LECTURE SEULE. Aucun ordre reel.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"

CIBLES = {
    "ml_diagnostics": "IDEA-09 / #166 -- SHAP",
    "microstructure_extras": "IDEA-12 / #169 -- Hawkes",
    "regime_detection": "IDEA-83+84 / #240+#241 -- Kalman + GARCH",
    "regime_label": "(voisin : est-il vivant ?)",
    "regime_wiring": "(voisin : est-il vivant ?)",
}


def _imports(fichier: Path) -> set[str]:
    """Les modules de `backtesting/` reellement importes par ce fichier."""
    out: set[str] = set()
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return out
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module.startswith("hl_observer.backtesting."):
                out.add(n.module.split(".")[-1])
            elif n.module == "hl_observer.backtesting":
                out |= {a.name for a in n.names}
            elif n.module.startswith(".") and n.module.lstrip("."):
                out.add(n.module.lstrip(".").split(".")[-1])
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("hl_observer.backtesting."):
                    out.add(a.name.split(".")[-1])
    return out


def _a_un_main(fichier: Path) -> bool:
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return False
    for n in arbre.body:
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            t = n.test
            if (isinstance(t.left, ast.Name) and t.left.id == "__name__"
                    and any(isinstance(c, ast.Constant) and c.value == "__main__"
                            for c in t.comparators)):
                return True
    return False


def _ligne_commentee(l: str) -> bool:
    t = l.strip().lower()
    return t.startswith("#") or t.startswith("rem ") or t.startswith("::")


def _portes_lanceurs(noms: set[str]) -> dict[str, list[str]]:
    portes: dict[str, list[str]] = {n: [] for n in noms}
    fichiers = list((RACINE / "tools").glob("*.ps1")) + list(RACINE.glob("*.cmd"))
    fichiers += list((RACINE / "tools").glob("*.py"))
    for f in fichiers:
        try:
            texte = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if f.suffix == ".py":
            for m in _imports(f) & noms:
                portes[m].append("%s (import)" % f.name)
            continue
        for ligne in texte.splitlines():
            if _ligne_commentee(ligne):
                continue
            for m in noms:
                if ("-m hl_observer.backtesting.%s" % m) in ligne:
                    portes[m].append("%s (-m)" % f.name)
    return portes


def main() -> int:
    print("\n" + "=" * 78)
    print("  QUI APPELLE VRAIMENT ? (AST -- pas un grep)")
    print("=" * 78)

    fichiers_src = [p for p in SRC.rglob("*.py") if "__pycache__" not in p.as_posix()]
    tests = [p for p in (RACINE / "tests").rglob("*.py") if "__pycache__" not in p.as_posix()]

    portes = _portes_lanceurs(set(CIBLES))

    for cible, quoi in CIBLES.items():
        chemin = SRC / "backtesting" / ("%s.py" % cible)
        appelants_src = []
        for f in fichiers_src:
            if f.stem == cible:
                continue
            if cible in _imports(f):
                rel = f.relative_to(SRC).as_posix()
                # un module de backtesting/ qui est lui-meme mort ne cable rien
                appelants_src.append(rel)
        appelants_tests = [f.name for f in tests if cible in _imports(f)]

        print("\n  --- %s   (%s)" % (cible, quoi))
        print("      existe            : %s" % chemin.exists())
        if chemin.exists():
            print("      bloc __main__     : %s" % _a_un_main(chemin))
        print("      importe par SRC   : %s" % (", ".join(appelants_src) or "PERSONNE"))
        print("      lance par un outil: %s" % (", ".join(portes[cible]) or "PERSONNE"))
        print("      importe par TESTS : %s" % (", ".join(appelants_tests) or "personne"))
        vivant = bool(appelants_src) or bool(portes[cible]) or (
            chemin.exists() and _a_un_main(chemin))
        print("      VERDICT           : %s" % ("VIVANT" if vivant else ">>> MORT <<<"))

    print("\n" + "=" * 78)
    print("  Rappel : un test qui importe un module NE LE CABLE PAS.")
    print("=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
