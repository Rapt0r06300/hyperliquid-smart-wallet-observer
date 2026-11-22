r"""Bilan du registre des essais de la mission 2 : combien d'essais, sur quels segments, quels statuts,
et à quel niveau un NOUVEL essai devrait conclure pour que l'ensemble reste honnête (Bonferroni).

Pourquoi : pendant 25 essais, chacun a été jugé à 95 % comme s'il était seul. Ce bilan rend visible
la correction globale et les segments encore VIERGES. Lecture seule.
"""
from __future__ import annotations

import collections
import json
import sys

import goal2_commun as G

#: Segments déjà consultés pour des FILLS, d'après le journal (mise à jour manuelle et datée).
CONSULTES = {"exploration": "consulté (exploration)", "execution_a": "consulté (L2-fin, L12, L12b)",
             "execution": "consulté via ses deux moitiés A et B",
             "validation": "CONSOMMÉ (H15b, 22/11 ; avant : courbes de vaults V5 HLP)",
             "execution_b": "consulté une fois (L12c, 22/11)", "oos_final": "parcouru par le labo le 20/11"}


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    lignes = [json.loads(x) for x in G.REGISTRE.read_text(encoding="utf-8").splitlines() if x.strip()]
    n = len(lignes)
    statuts = collections.Counter(str(x.get("statut")) for x in lignes)
    segments = collections.Counter(str(x.get("segment")) for x in lignes)
    print(f"  essais enregistres : {n}")
    print(f"  par statut  : {dict(statuts.most_common())}")
    print(f"  par segment : {dict(segments.most_common())}")
    print(f"  niveau corrige pour un NOUVEL essai (Bonferroni, {n + 1} essais) : {100 * (1 - 0.05 / (n + 1)):.3f} %"
          f"  (alpha {0.05 / (n + 1):.5f})")
    print("  segments :")
    for s in G.SEGMENTS:
        print(f"    {s:<12} {CONSULTES.get(s, 'VIERGE pour les fills')}")
    print("  derniers essais :")
    for x in lignes[-6:]:
        print(f"    {str(x.get('hypothese'))[:44]:<45} {str(x.get('segment')):<14} {x.get('statut')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
