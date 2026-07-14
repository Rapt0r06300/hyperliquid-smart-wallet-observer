"""IMPROVE-14 (#121) — pose (ou ABAISSE) la baseline du cliquet de couverture.

Il ne peut que la faire DESCENDRE. `ecrire_baseline` refuse de la remonter : un cliquet qui
se relache tout seul n'est pas un cliquet.

    python tools/poser_baseline_couverture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.audit.couverture import auditer, ecrire_baseline, lire_baseline  # noqa: E402

IGNORE = ("__pycache__", "_archive", "DISABLED")


def _collecter(motifs):
    out = {}
    for motif in motifs:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if any(x in rel for x in IGNORE):
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return out


def main() -> int:
    py = _collecter(("src/**/*.py", "tests/**/*.py"))
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1"))
    v = auditer(py, lanceurs)
    avant = lire_baseline(RACINE)

    print("joignables (production) : %d" % v.n_joignables)
    print("couverts par un test    : %d" % v.n_couverts)
    print("NON TESTES              : %d   (%.1f %% de couverture)" % (v.n_non_testes, 100 * v.taux))
    print("baseline actuelle       : %s" % avant)

    if avant is None or v.n_non_testes < avant:
        ecrire_baseline(RACINE, v.n_non_testes, note="cliquet IMPROVE-14 : ne peut que DESCENDRE")
        print("-> baseline posee a %d" % v.n_non_testes)
    elif v.n_non_testes > avant:
        print("-> 🔴 REGRESSION : %d modules non testes de PLUS que la baseline." % (v.n_non_testes - avant))
        print("   La baseline n'est PAS relevee. Ecris les tests manquants.")
        for m in v.non_testes[-15:]:
            print("     %s" % m)
        return 1
    else:
        print("-> inchangee.")

    print()
    print("Les 15 derniers non testes (par ordre alphabetique) :")
    for m in v.non_testes[-15:]:
        print("  %s" % m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
