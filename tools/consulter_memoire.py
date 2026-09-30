#!/usr/bin/env python3
"""EST-CE QUE CETTE IDEE EST DEJA MORTE ? (2026-07-12)

    fail -> investigate -> distil -> CONSULT

Avant de lancer un backtest, de rerégler un seuil, de proposer une piste : DEMANDE ICI.

Chaque zone morte du registre a coute des jours de travail. Elle porte sa mesure, son
echantillon, et la condition exacte qui la rouvrirait. Ce n'est pas une liste d'opinions.

    python tools/consulter_memoire.py "baisser min_edge pour ouvrir plus de trades"
    python tools/consulter_memoire.py                 # liste tout le cimetiere

A DESTINATION DE : Flo, Claude, Codex, et tout ce qui viendra apres.

LECTURE SEULE. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.agent.dead_zones_hypersmart import registre_officiel  # noqa: E402


def _lister() -> int:
    r = registre_officiel()
    print("\n" + "=" * 78)
    print("  LE CIMETIERE — %d hypotheses TUEES PAR UNE MESURE" % len(r.zones))
    print("=" * 78)
    for z in r.zones:
        print("\n  [%s]  %s" % (z.id, z.date))
        print("     on croyait : %s" % z.hypothese)
        print("     la mesure  : %s = %+.4g %s  (sur %s observations)"
              % (z.mesure, z.valeur, z.unite, format(z.echantillon, ",").replace(",", " ")))
        print("     verdict    : %s" % z.verdict)
        print("     LECON      : %s" % z.lecon)
        print("     rouvrir si : %s" % z.condition_de_reouverture)
    print("\n" + "=" * 78)
    print("  Une zone morte n'est PAS un dogme : chacune dit ce qui la rouvrirait.")
    print("  Mais on ne re-paie pas une impasse deja payee.")
    print("=" * 78 + "\n")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        return _lister()

    idee = " ".join(sys.argv[1:])
    r = registre_officiel()
    touches = r.consulter(idee)

    print("\n  IDEE : %s\n" % idee)
    if not touches:
        print("  " + "-" * 74)
        print("  >>> LIBRE. Aucune zone morte touchee.")
        print("  " + "-" * 74)
        print("      Rien dans la memoire ne l'interdit. Mesure-la, et quel que soit le")
        print("      resultat, ENTERRE-LA ici si elle echoue -- pour que personne n'y revienne.\n")
        return 0

    print("  " + "-" * 74)
    print("  >>> DEJA MORT. Cette idee a DEJA ete testee et tuee.")
    print("  " + "-" * 74)
    for z in touches:
        print("\n  [%s]  %s" % (z.id, z.date))
        print("     mesure  : %s = %+.4g %s  (sur %s observations)"
              % (z.mesure, z.valeur, z.unite, format(z.echantillon, ",").replace(",", " ")))
        print("     verdict : %s" % z.verdict)
        print("     LECON   : %s" % z.lecon)
        print("\n     ROUVRIR SEULEMENT SI : %s" % z.condition_de_reouverture)
    print("\n  Ne relance PAS ce backtest. Il a deja parle.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
