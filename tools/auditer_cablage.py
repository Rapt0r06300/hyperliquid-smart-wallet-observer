#!/usr/bin/env python3
"""T3 -- « QUI APPELLE CE MODULE ? » applique au VRAI depot (2026-07-12).

    python tools/auditer_cablage.py

Trois questions, une seconde, et cinq semaines de bugs qu'on n'aurait pas eus :

  1. quels modules PERSONNE n'importe ?                          -> code mort franc
  2. quels modules SEULS LES TESTS importent ?                   -> teste mais NON BRANCHE
  3. quels interrupteurs le code lit-il... que personne ne pose ? -> capacite eteinte A JAMAIS

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.audit.cablage import (  # noqa: E402
    auditer_les_interrupteurs,
    auditer_les_modules,
)

PREFIXES_NOS_FLAGS = ("HYPERSMART_", "HL_", "V26_", "V27_", "HYPER_", "SIM_", "PAPER_")

# 🚩 BUG CORRIGE LE 2026-07-12 (T3c) -- L'AUDIT AVAIT UN ANGLE MORT.
#
# L'ancien filtre etait un `in` sur la chaine complete :
#
#     IGNORE = (..., "runtime/", ..., "_archive", ...)
#     if any(x in rel for x in IGNORE): continue
#
# Intention : sauter le dossier de DONNEES `runtime/` a la RACINE (logs, etat, DB).
# Effet reel : `src/hl_observer/runtime/hot_path.py` contient aussi "runtime/" ->
# **tout le paquet de PRODUCTION `src/hl_observer/runtime/` etait invisible** :
# hot_path, event_driven_decider, persistent_poll_runner, bounded_event_queue,
# graceful_shutdown, safe_mode... soit le coeur du travail P4/P5.
# Idem "_archive" qui mangeait `src/hl_observer/release/clean_archive.py`.
#
# Consequence : l'audit ne les declarait pas VIVANTS -- il ne les VOYAIT PAS. Un module
# invisible ne peut jamais etre declare mort. C'est le plus sournois des angles morts :
# l'outil qui cherche le code mort en cachait lui-meme huit.
#
# Le filtre est desormais ANCRE : soit un prefixe de chemin depuis la racine, soit un
# SEGMENT de chemin entier. Jamais une sous-chaine.

# dossiers de la RACINE qui ne sont pas du code (donnees, logs, etat)
IGNORE_PREFIXES = ("runtime/", "data/", "logs/", ".git/", "node_modules/")
# segments de chemin entiers, ou qu'ils soient
IGNORE_SEGMENTS = ("__pycache__", "cli_pkg_DISABLED", "_archive")


def _a_ignorer(rel: str) -> bool:
    if any(rel.startswith(p) for p in IGNORE_PREFIXES):
        return True
    return any(seg in IGNORE_SEGMENTS for seg in rel.split("/"))


def _lire(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return ""


def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in ROOT.glob(motif):
            rel = p.relative_to(ROOT).as_posix()
            if _a_ignorer(rel):
                continue
            out[rel] = _lire(p)
    return out


def main() -> int:
    # #597 : les OUTILS sont un corpus a part -- ce ne sont pas des modules du bot, ce sont des
    # PORTES (`python tools\\x.py` dans un .cmd). Les melanger au code faussait le verdict.
    py = _collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    outils = _collecter(("tools/**/*.py",))
    # 🔴 REGRESSION TROUVEE LE 18/07 : les lanceurs de recherche ont ete DEMENAGES dans
    # `outils de test/` (rangement du 14/07). Ce glob ne regardait que la racine et `tools/`
    # -> du jour au lendemain, l'audit a cesse de VOIR les portes `python tools\x.py`, et a
    # declare MORTS les moteurs qu'on lance le plus souvent (overfit_selection, H-181...).
    # Personne n'avait bouge une ligne de code : deplacer un .cmd avait suffi.
    # Lecon : la liste des portes doit suivre les portes, sinon l'audit ment sans le savoir.
    lanceurs = _collecter(("*.cmd", "tools/**/*.cmd", "tools/**/*.ps1",
                           "outils de test/**/*.cmd", "outils de test/**/*.ps1",
                           "*.ps1", "*.sh", "config/**/*.yaml", "config/**/*.yml"))

    print("\n" + "=" * 78)
    print(" T3 -- AUDIT DE CABLAGE   (%d fichiers .py, %d outils, %d lanceurs)"
          % (len(py), len(outils), len(lanceurs)))
    print("=" * 78)

    # T3d : les LANCEURS declarent des points d'entree (`python -m hl_observer.X`) que l'AST
    # ne peut pas voir. Sans eux, tout ce que le poller de simulation importe passe pour mort.
    # #597 : et les OUTILS en declarent d'autres (`python tools\\x.py`). Sans eux, toute la
    # recherche -- `scenario_search` compris -- passe pour morte. C'etait le cas jusqu'au 13/07.
    v = auditer_les_modules(py, lanceurs=lanceurs, outils=outils)
    inters = auditer_les_interrupteurs({**py, **outils}, lanceurs, prefixes=PREFIXES_NOS_FLAGS)
    morts = [i for i in inters if i.mort]

    # ---------------------------------------------------------------- 0. L'AUDIT SE JUGE LUI-MEME
    # Si un fichier n'a pas pu etre parse (mount qui tronque `cli.py`, fichier casse), il
    # "n'importe rien" -- et tout ce qu'il appelait tomberait en "mort". On ne rend PAS un
    # verdict la-dessus. Mieux vaut pas de chiffre qu'un faux chiffre.
    if not v.fiable:
        print("\n  !!! AUDIT NON FIABLE : %d fichier(s) illisible(s) (AST)." % len(v.illisibles))
        for f in v.illisibles[:20]:
            print("      %s" % f)
        print("\n  Ces fichiers 'n'importent rien' pour l'AST -> tout ce qu'ils appellent")
        print("  apparaitrait MORT. Le mount tronque les gros fichiers : relancer sous Windows.")
        print("  AUCUN VERDICT RENDU.\n")
        return 2

    # ---------------------------------------------------------------- 3. LE PLUS DANGEREUX
    print("\n" + "-" * 78)
    print(" 3. INTERRUPTEURS MORTS -- lus par le code, poses par PERSONNE, defaut ETEINT")
    print("-" * 78)
    print("    C'est le bug du poller L2, mot pour mot : la capacite existe, elle est cablee,")
    print("    elle est testee... et elle ne s'allumera JAMAIS. Sans un log. Sans une erreur.\n")
    if not morts:
        print("    AUCUN. (%d interrupteurs a nous, tous poses ou allumes par defaut)\n" % len(inters))
    else:
        for i in sorted(morts, key=lambda x: -len(x.lu_par)):
            print("    %-42s defaut=%-6r  lu par %d fichier(s)"
                  % (i.nom, i.defaut, len(i.lu_par)))
            for f in i.lu_par[:4]:
                print("        %s" % f)
            if len(i.lu_par) > 4:
                print("        ... et %d autre(s)" % (len(i.lu_par) - 4))
        print("\n    >>> %d capacite(s) presente(s) et ETEINTE(S) EN SILENCE.\n" % len(morts))

    ambigus = [i for i in inters if i.ambigu]
    if ambigus:
        print("    A LIRE A LA MAIN (defaut VIDE : 'aucune limite' ou 'eteint' ? on ne tranche pas) :")
        for i in ambigus:
            print("      %-42s lu par %s" % (i.nom, ", ".join(i.lu_par)))
        print()

    # ---------------------------------------------------------------- 2. LA SIGNATURE DU PROJET
    print("-" * 78)
    print(" 2. TESTES MAIS NON BRANCHES -- seuls les tests les importent")
    print("-" * 78)
    print("    Le pire des deux mondes : la suite est VERTE, la capacite existe, elle a des")
    print("    tests... et aucun chemin de production ne l'appelle. C'est `delta_neutral_carry`,")
    print("    trouve pendant T2 -- par accident, apres des semaines.\n")
    if not v.testes_non_branches:
        print("    aucun.\n")
    else:
        for m in v.testes_non_branches:
            print("    %s" % m)
        print("\n    >>> %d module(s) teste(s) mais JAMAIS appele(s) en production.\n"
              % len(v.testes_non_branches))

    # ---------------------------------------------------------------- 1. le code mort franc
    print("-" * 78)
    print(" 1. ORPHELINS -- personne ne les importe, pas meme un test")
    print("-" * 78)
    if not v.orphelins:
        print("    aucun.\n")
    else:
        print("    %d module(s). Les 30 premiers :\n" % len(v.orphelins))
        for m in v.orphelins[:30]:
            print("    %s" % m)
        if len(v.orphelins) > 30:
            print("    ... et %d autre(s)" % (len(v.orphelins) - 30))
        print()

    # ---------------------------------------------------------------- 0bis. LA RECHERCHE (#597)
    print("-" * 78)
    print(" 0. OUTILLES -- inatteignables depuis le BOT, mais lances par un OUTIL de recherche")
    print("-" * 78)
    print("    Ce ne sont PAS des morts : `python tools\\x.py` dans un .cmd est une PORTE.")
    print("    Ce ne sont PAS des vivants non plus : le bot ne les execute jamais.")
    print("    (Un garde-fou de risk/ qui tomberait ici serait un MORT : voir le test")
    print("     test_aucun_garde_fou_de_PRODUCTION_ne_survit_par_un_simple_OUTIL.)\n")
    if not v.outilles:
        print("    aucun.\n")
    else:
        for m in v.outilles:
            print("    %s" % m)
        print("\n    >>> %d module(s) de RECHERCHE, joignables seulement par un outil.\n"
              % len(v.outilles))

    out = ROOT / "data" / "reports" / "audit_cablage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    rapport = v.as_dict()
    rapport["interrupteurs_morts"] = [i.as_dict() for i in morts]
    rapport["interrupteurs_vivants"] = [i.as_dict() for i in inters if not i.mort]
    out.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  rapport complet : %s\n" % out.relative_to(ROOT))

    return 0


if __name__ == "__main__":
    sys.exit(main())
