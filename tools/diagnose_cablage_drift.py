"""Diagnostic read-only du cliquet global de câblage.

Utilise exactement le même moteur et le même périmètre que
``tests/test_risk_guards_no_limbo.py`` afin de nommer les modules
``testes_non_branches`` hors dette déclarée. Aucun seuil n'est modifié.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.audit.cablage import auditer_les_modules
from hl_observer.audit.dette_cablage import DETTE_CABLAGE, est_dette

ROOT = Path(__file__).resolve().parents[1]


def _sources(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for path in ROOT.glob(motif):
            rel = path.relative_to(ROOT).as_posix()
            if "__pycache__" in rel:
                continue
            try:
                out[rel] = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
    return out


def main() -> int:
    fichiers = _sources(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    lanceurs = _sources(
        (
            "*.cmd",
            "*.ps1",
            "*.sh",
            "tools/**/*.ps1",
            "tools/**/*.cmd",
            "outils de test/**/*.cmd",
            "outils de test/**/*.ps1",
        )
    )
    outils = _sources(("tools/**/*.py",))
    verdict = auditer_les_modules(fichiers, lanceurs=lanceurs, outils=outils)
    if not verdict.fiable:
        print(f"AUDIT_NON_FIABLE={len(verdict.illisibles)}")
        for item in verdict.illisibles[:20]:
            print(f"ILLISIBLE={item}")
        return 2

    declares = sorted(m for m in verdict.testes_non_branches if est_dette(m))
    hors_dette = sorted(m for m in verdict.testes_non_branches if not est_dette(m))
    print(f"DETTE_REGISTRE={len(DETTE_CABLAGE)}")
    print(f"TESTES_NON_BRANCHES_TOTAL={len(verdict.testes_non_branches)}")
    print(f"TESTES_NON_BRANCHES_DECLARES={len(declares)}")
    print(f"TESTES_NON_BRANCHES_HORS_DETTE={len(hors_dette)}")
    print("BEGIN_HORS_DETTE")
    for module in hors_dette:
        print(module)
    print("END_HORS_DETTE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
