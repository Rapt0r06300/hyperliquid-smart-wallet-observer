#!/usr/bin/env python3
"""T3d -- LE HOT PATH EST-IL VRAIMENT MORT ? On le PROUVE, on ne le suppose pas.

    python tools/prouver_hot_path.py

L'audit de cablage lit l'AST. C'est une borne SUPERIEURE : ce qu'il declare mort l'est
vraiment... *sauf* s'il existe un chemin que l'AST ne peut pas voir. Il y en a exactement
quatre :

  1. `importlib.import_module("hl_observer.runtime.hot_path")`  -- import par CHAINE
  2. `__import__("...")`                                        -- idem
  3. `python -m hl_observer.runtime.hot_path` dans un lanceur   -- sous-processus
  4. une reference par chaine dans une config (yaml/json/ps1/cmd)

Ce script cherche les quatre, PUIS fait la seule preuve qui vaille : il importe les VRAIS
points d'entree de production et regarde ce qui atterrit dans `sys.modules`.

REGLE DU PROJET (12/07) : reproduire par EXECUTION avant d'accuser.

Lecture seule. Aucun ordre, aucune cle, aucune signature. Aucun serveur n'est demarre :
on ne fait qu'IMPORTER (les `if __name__ == "__main__"` ne se declenchent pas).
"""

from __future__ import annotations

import importlib
import re
import sys
import traceback
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

# Les 10 modules que l'audit, une fois son angle mort corrige, declare MORTS.
SUSPECTS = (
    "hl_observer.runtime.hot_path",
    "hl_observer.runtime.event_driven_decider",
    "hl_observer.runtime.persistent_poll_runner",
    "hl_observer.runtime.bounded_event_queue",
    "hl_observer.runtime.detailed_logger",
    "hl_observer.runtime.detailed_report",
    "hl_observer.runtime.graceful_shutdown",
    "hl_observer.runtime.safe_mode",
    "hl_observer.runtime.research_path",
    "hl_observer.release.clean_archive",
)

# Tout ce qui n'est pas du code de production : on ne compte pas leurs mentions comme
# une preuve de vie.
NON_PRODUCTION = ("tests/", "tools/", "docs/", "data/", "logs/", "__pycache__",
                  "runtime/", ".git/", "_archive", "cli_pkg_DISABLED")


def _hors_production(rel: str) -> bool:
    return any(x in rel for x in NON_PRODUCTION)


# ATTENTION : le depot contient `runtime/research/github_repos_v24/` = **5 617 repos clones**.
# Un `RACINE.glob("**/*.py")` marche donc des centaines de milliers de fichiers. On NE balaie
# QUE le code du bot et ses lanceurs, et on ne le fait qu'UNE SEULE FOIS.
def _fichiers_a_fouiller() -> list[tuple[str, str]]:
    """(chemin relatif, contenu) -- le code du bot + TOUT ce qui peut lancer un module :
    lanceurs .cmd/.ps1/.sh a la racine, et les configs."""
    exts_config = (".yaml", ".yml", ".json", ".toml", ".cfg", ".ini")
    chemins: list[Path] = []

    chemins += [p for p in (RACINE / "src").rglob("*.py")]
    chemins += [p for p in (RACINE / "hyper_smart_observer").rglob("*.py")
                if (RACINE / "hyper_smart_observer").is_dir()]
    # les lanceurs : c'est LA ou se cacherait un `python -m hl_observer.runtime.hot_path`
    for motif in ("*.cmd", "*.ps1", "*.sh", "*.bat"):
        chemins += list(RACINE.glob(motif))
        chemins += list((RACINE / "tools").glob(motif))
    for d in ("config", "configs"):
        if (RACINE / d).is_dir():
            chemins += [p for p in (RACINE / d).rglob("*") if p.suffix in exts_config]

    out: list[tuple[str, str]] = []
    for p in chemins:
        if not p.is_file():
            continue
        rel = p.relative_to(RACINE).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            out.append((rel, p.read_text(encoding="utf-8-sig", errors="ignore")))
        except OSError:
            continue
    return out


# ============================================================ 1. LES IMPORTS DYNAMIQUES


def chercher_imports_dynamiques(fichiers: list[tuple[str, str]]) -> list[tuple[str, int, str]]:
    """`importlib.import_module(...)` / `__import__(...)` : les seuls imports que l'AST
    ne resout pas. S'il y en a un qui vise un suspect, l'audit s'est trompe."""
    motif = re.compile(r"(importlib\.import_module|__import__|importlib\.util\.spec_from)")
    trouves = []
    for rel, texte in fichiers:
        if not rel.endswith(".py") or _hors_production(rel):
            continue
        for i, ligne in enumerate(texte.splitlines(), 1):
            if motif.search(ligne):
                trouves.append((rel, i, ligne.strip()))
    return trouves


# ============================================================ 2. LES MENTIONS PAR CHAINE


# 🚩 LECON DU 12/07, APPLIQUEE A MON PROPRE OUTIL.
#
# Ma 1re version cherchait la SOUS-CHAINE "hot_path". Elle a rendu 35 "mentions"... dont
# `snapshot_path` (s-n-a-p-**s-hot_path**). C'est EXACTEMENT le bug du filtre `IGNORE` que je
# venais de corriger dans l'audit -- reproduit dans l'outil cense le verifier.
#
# On cherche donc le nom entre FRONTIERES DE MOT. Et surtout on separe deux choses que ma 1re
# version confondait :
#
#   * une MENTION      = le nom apparait dans une chaine de texte. Inoffensif.
#   * un IMPORT/LANCEMENT = `import X`, `from X import`, `python -m X`, `spec_from_file(X)`.
#                        C'est la SEULE chose qui peut ressusciter un module.
#
# Un module cite dans une liste de mots-cles n'est pas vivant. Il est cite.

_LANCEMENT = re.compile(
    r"(^\s*import\s|^\s*from\s|\bimport_module\s*\(|__import__\s*\(|"
    r"-m\s+hl_observer|spec_from_file_location|\bimportlib\b)"
)


def chercher_mentions(
    fichiers: list[tuple[str, str]], module: str
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Rend (LANCEMENTS, mentions_inoffensives).

    Les LANCEURS (.cmd/.ps1/.sh) ne sont JAMAIS filtres par `_hors_production` : le lanceur
    reel du bot est `tools/start_hypersmart_simulation.ps1`, et c'est precisement la qu'un
    `python -m hl_observer.runtime.hot_path` se cacherait.
    """
    court = module.rsplit(".", 1)[-1]
    # frontieres de mot : `\bhot_path\b` ne matche PAS dans `snapshot_path`.
    motif = re.compile(r"(?<![\w.])" + re.escape(court) + r"\b")
    motif_complet = re.compile(re.escape(module))

    lancements: list[tuple[str, int, str]] = []
    mentions: list[tuple[str, int, str]] = []

    for rel, texte in fichiers:
        est_un_lanceur = rel.endswith((".cmd", ".ps1", ".sh", ".bat"))
        if not est_un_lanceur and _hors_production(rel):
            continue
        if court not in texte:
            continue
        for i, ligne in enumerate(texte.splitlines(), 1):
            if not (motif.search(ligne) or motif_complet.search(ligne)):
                continue
            entree = (rel, i, ligne.strip()[:110])
            # un lancement, c'est soit une vraie ligne d'import, soit un `python -m` dans un
            # lanceur. Tout le reste n'est qu'une chaine de caracteres.
            if _LANCEMENT.search(ligne) or (est_un_lanceur and "-m " in ligne):
                lancements.append(entree)
            else:
                mentions.append(entree)
    return lancements, mentions


# ============================================================ 3. LA PREUVE PAR EXECUTION


def points_d_entree_reels() -> list[str]:
    """Ce que le lanceur demarre VRAIMENT :
       LANCER_HYPERSMART.cmd -> start_hypersmart_simulation.ps1 -> `python -m hl_observer ui`
    Donc : hl_observer.__main__, hl_observer.cli, et tout le paquet ui/.
    """
    entrees = ["hl_observer.__main__", "hl_observer.cli"]
    d = RACINE / "src" / "hl_observer" / "ui"
    if d.is_dir():
        for p in sorted(d.glob("*.py")):
            if p.stem == "__init__":
                entrees.append("hl_observer.ui")
            else:
                entrees.append("hl_observer.ui.%s" % p.stem)
    return entrees


def importer_la_production() -> tuple[set[str], list[tuple[str, str]]]:
    """Importe les points d'entree REELS et rend l'ensemble des modules hl_observer.*
    effectivement charges. C'est la preuve par EXECUTION : plus aucun AST, plus aucune
    supposition -- Python lui-meme dit ce qu'il charge.

    Note : importer un module n'execute pas son `if __name__ == "__main__"`. Aucun
    serveur ne demarre, aucune socket ne s'ouvre.
    """
    echecs: list[tuple[str, str]] = []
    for nom in points_d_entree_reels():
        try:
            importlib.import_module(nom)
        except Exception as exc:            # noqa: BLE001 -- on VEUT tout attraper
            echecs.append((nom, "%s: %s" % (type(exc).__name__, exc)))
    charges = {m for m in sys.modules if m.startswith("hl_observer")}
    return charges, echecs


# ============================================================ VERDICT


def main() -> int:
    print("=" * 78)
    print(" T3d -- LE HOT PATH P4/P5 EST-IL VRAIMENT MORT ?")
    print(" On ne suppose pas : on cherche les 4 chemins invisibles a l'AST, puis on EXECUTE.")
    print("=" * 78)

    fichiers = _fichiers_a_fouiller()
    print("\n  (perimetre fouille : %d fichiers -- code du bot + lanceurs + configs.\n"
          "   Le dossier runtime/research/github_repos_v24/ (5 617 repos clones) est EXCLU.)"
          % len(fichiers))

    # --- 1
    print("\n[1/3] IMPORTS DYNAMIQUES dans le code de production (invisibles a l'AST)")
    dyn = chercher_imports_dynamiques(fichiers)
    if not dyn:
        print("      AUCUN. Le code de production n'importe jamais par chaine.")
        print("      -> l'AST voit donc TOUS les imports. Sa borne est exacte.")
    else:
        for rel, i, ligne in dyn:
            print("      %s:%d  %s" % (rel, i, ligne))
        print("      /!\\ A LIRE : si l'un vise un suspect, l'audit s'est trompe.")

    # --- 2
    print("\n[2/3] IMPORTS / LANCEMENTS par chaine (python -m, config, lanceur...)")
    print("      On separe un LANCEMENT (import / python -m : ca ressuscite) d'une simple")
    print("      MENTION (une chaine de texte : inoffensif).\n")
    ressuscites = []
    for module in SUSPECTS:
        court = module.rsplit(".", 1)[-1]
        lancements, mentions = chercher_mentions(fichiers, module)
        if lancements:
            print("      %-42s /!\\ %d LANCEMENT(S) :" % (court, len(lancements)))
            for rel, i, ligne in lancements[:6]:
                print("            %s:%d  %s" % (rel, i, ligne))
            ressuscites.append(court)
        elif mentions:
            print("      %-42s 0 lancement, %d mention(s) inoffensive(s) :"
                  % (court, len(mentions)))
            for rel, i, ligne in mentions[:3]:
                print("            (texte) %s:%d  %s" % (rel, i, ligne))
        else:
            print("      %-42s RIEN. Pas meme son nom." % court)

    # --- 3
    print("\n[3/3] PREUVE PAR EXECUTION -- on importe les VRAIS points d'entree")
    for e in points_d_entree_reels():
        print("      import %s" % e)
    charges, echecs = importer_la_production()
    print("\n      -> %d module(s) hl_observer.* effectivement charges par Python." % len(charges))
    if echecs:
        print("      /!\\ %d point(s) d'entree n'ont PAS pu etre importes :" % len(echecs))
        for nom, err in echecs:
            print("            %s -> %s" % (nom, err))
        print("      Un point d'entree non importe = un trou dans la preuve. On le dit.")

    print("\n" + "=" * 78)
    print(" VERDICT")
    print("=" * 78)
    vivants, morts = [], []
    for module in SUSPECTS:
        (vivants if module in charges else morts).append(module)

    if vivants:
        print("\n  VIVANTS (charges par Python au demarrage de la production) :")
        for m in vivants:
            print("      %s" % m)
        print("\n  >>> L'AUDIT S'EST TROMPE sur ceux-la. Ne PAS les enterrer.")
    else:
        print("\n  AUCUN des 10 suspects n'est charge par la production.")

    if morts:
        print("\n  MORTS -- PROUVE PAR EXECUTION (Python ne les charge JAMAIS) :")
        for m in morts:
            print("      %s" % m)

    if not echecs and not dyn and not ressuscites and morts:
        print("\n  Les 3 controles concordent :")
        print("    * aucun import dynamique dans le code de production ;")
        print("    * aucune mention par chaine (ni lanceur, ni config) ;")
        print("    * Python ne les charge pas en important les points d'entree reels.")
        print("\n  Ce n'est plus « probablement mort ». C'est MORT.")
    else:
        print("\n  /!\\ Au moins un controle n'est pas concluant -> lire ci-dessus AVANT de trancher.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
