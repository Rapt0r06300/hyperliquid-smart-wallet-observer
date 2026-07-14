"""Le cliquet dit « 304 morts, plafond 303 ». QUI est le 304e ?

On ne releve JAMAIS le plafond pour faire taire l'alarme (c'est tout l'interet d'un cliquet).
On identifie le module, et on le BRANCHE ou on l'ENTERRE.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.audit.cablage import auditer_les_modules  # noqa: E402

MOTIFS = ("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py", "tools/**/*.py")


def _sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in MOTIFS:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if "__pycache__" in rel:
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
    return out


v = auditer_les_modules(_sources())
morts = sorted(v.testes_non_branches)

print("modules testes-mais-NON-branches : %d (plafond 303)" % len(morts))
print()
print("--- suspects : les modules AJOUTES depuis que le plafond a ete pose (12/07) ---")
NEUFS = ("regime_wiring", "regime_label", "latency_journal", "audit.couverture", "couverture")
for m in morts:
    if any(n in m for n in NEUFS):
        print("  >>> %s" % m)
print()
print("--- tous les morts contenant 'audit', 'runtime' ou 'backtesting' ---")
for m in morts:
    if any(n in m for n in ("audit", "runtime", "backtesting")):
        print("  %s" % m)
