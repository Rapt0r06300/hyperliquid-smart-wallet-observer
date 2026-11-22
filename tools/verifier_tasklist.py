"""TASKLIST.md contient-il TOUTES les taches, sans exception ?

⚠️ NE PAS faire ce controle depuis le sandbox : le mount TRONQUE le fichier (il voyait 602 lignes
la ou Windows en compte 664). Un outil de mesure qui lit un fichier tronque ment. Ici, on lit
Windows, qui fait foi.

Sortie : la liste des IDs MANQUANTS, et rien d'autre. Aucun ID n'est invente.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FICHIER = RACINE / "docs" / "archive" / "root-history" / "TASKLIST.md"

# Le systeme de taches va de #56 a #599. #353 n'a jamais existe (trou de numerotation).
ATTENDUS = set(range(56, 600)) - {353}

# Une ligne de tache peut prendre plusieurs formes :
#   - [ ] **#123** — ...      (en attente)
#   - [x] #123 — ...          (terminee, forme courte)
#   - [x] ~~**#595**~~ — ...  (terminee barree)
#   - ⏳ **#115** — ...        (bloquee)
LIGNE_TACHE = re.compile(r"^\s*-\s*(?:\[[ x]\]|⏳|✅|🔴|⚠️)?\s*~*\**#(\d+)\b")


def main() -> int:
    # Sortie journalisable : hors console, Windows encode la sortie en cp1252 et un
    # caractere exotique imprime tue l'outil. Mesure du 21/11/2026 :
    # `conduire_labo_par_tranches.py` lisait 10 631 645 fills en 12 s puis mourait sur
    # la fleche de << -> N tranches >> des que sa sortie partait dans un fichier.
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105 -- idiome du depot ; contextlib ici couterait un import par outil
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    texte = FICHIER.read_text(encoding="utf-8", errors="replace")
    lignes = texte.splitlines()

    trouves: set[int] = set()
    for ligne in lignes:
        m = LIGNE_TACHE.match(ligne)
        if m:
            trouves.add(int(m.group(1)))

    manquants = sorted(ATTENDUS - trouves)
    en_trop = sorted(trouves - ATTENDUS)

    print("fichier         : %s" % FICHIER.name)
    print("lignes du .md   : %d" % len(lignes))
    print("IDs attendus    : %d  (#56..#599, sans #353)" % len(ATTENDUS))
    print("IDs TROUVES     : %d" % len(trouves & ATTENDUS))
    print("IDs MANQUANTS   : %d" % len(manquants))
    print()

    if manquants:
        print("=== MANQUANTS (a rajouter, sans en oublier un seul) ===")
        for i in manquants:
            print("  #%d" % i)
    else:
        print("✅ AUCUN MANQUANT : les 543 taches sont dans le fichier.")

    if en_trop:
        print()
        print("=== IDs presents mais HORS de la plage attendue (a verifier) ===")
        for i in en_trop:
            print("  #%d" % i)

    return 0 if not manquants else 1


if __name__ == "__main__":
    raise SystemExit(main())
