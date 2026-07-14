"""Pourquoi le nombre de modules MORTS a-t-il bouge ?

Compare le verdict de cablage MAINTENANT avec le dernier rapport ecrit dans
data/reports/audit_cablage.json. Repond a UNE question : quels modules sont ENTRES
dans la liste des morts, et lesquels en sont SORTIS.

Un cliquet qu'on deplace sans savoir pourquoi n'est plus un cliquet.

Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.audit.cablage import auditer_les_modules  # noqa: E402


def _charger_ancien(chemin: Path) -> tuple[set[str], set[str]]:
    if not chemin.is_file():
        return set(), set()
    data = json.loads(chemin.read_text(encoding="utf-8"))
    return set(data.get("testes_non_branches") or []), set(data.get("orphelins") or [])


def _sources() -> dict[str, str]:
    """MEME perimetre que tests/test_risk_guards_no_limbo.py -- sinon on compare deux choses
    differentes et le diff ment."""
    out: dict[str, str] = {}
    for motif in ("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"):
        for p in RACINE.glob(motif):
            if not p.is_file():
                continue
            try:
                out[str(p.relative_to(RACINE))] = p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
    return out


def _lanceurs() -> dict[str, str]:
    """T3d : un `python -m hl_observer.X` dans un .ps1 est un POINT D'ENTREE."""
    out: dict[str, str] = {}
    for motif in ("*.cmd", "*.ps1", "*.sh", "tools/**/*.ps1", "tools/**/*.cmd"):
        for p in RACINE.glob(motif):
            if p.is_file():
                try:
                    out[str(p.relative_to(RACINE))] = p.read_text(encoding="utf-8-sig", errors="ignore")
                except OSError:
                    continue
    return out


def _outils() -> dict[str, str]:
    """#597 : un `python tools\\x.py` dans un .cmd est un POINT D'ENTREE lui aussi. Sans eux,
    ce diff declarerait morte toute la recherche -- `scenario_search` compris."""
    out: dict[str, str] = {}
    for p in RACINE.glob("tools/**/*.py"):
        if p.is_file() and "__pycache__" not in p.as_posix():
            try:
                out[p.relative_to(RACINE).as_posix()] = p.read_text(encoding="utf-8-sig",
                                                                    errors="ignore")
            except OSError:
                continue
    return out


def main() -> int:
    ancien_morts, ancien_orph = _charger_ancien(RACINE / "data" / "reports" / "audit_cablage.json")
    v = auditer_les_modules(_sources(), lanceurs=_lanceurs(), outils=_outils())
    morts = set(v.testes_non_branches)
    orph = set(v.orphelins)

    print("=" * 78)
    print(" MORTS   : %4d  ->  %4d   (%+d)" % (len(ancien_morts), len(morts), len(morts) - len(ancien_morts)))
    print(" ORPHELINS: %4d  ->  %4d   (%+d)" % (len(ancien_orph), len(orph), len(orph) - len(ancien_orph)))
    print("=" * 78)

    entres = sorted(morts - ancien_morts)
    sortis = sorted(ancien_morts - morts)

    print("\n>>> ENTRES dans les MORTS (%d) -- c'est CA qu'il faut expliquer :" % len(entres))
    for m in entres:
        print("    + %s" % m)
    print("\n>>> SORTIS des MORTS (%d) -- branches avec succes :" % len(sortis))
    for m in sortis:
        print("    - %s" % m)

    e_o = sorted(orph - ancien_orph)
    s_o = sorted(ancien_orph - orph)
    print("\n>>> ENTRES dans les ORPHELINS (%d) :" % len(e_o))
    for m in e_o:
        print("    + %s" % m)
    print("\n>>> SORTIS des ORPHELINS (%d) :" % len(s_o))
    for m in s_o:
        print("    - %s" % m)

    if not v.fiable:
        print("\n!!! VERDICT NON FIABLE : %d fichier(s) illisible(s)" % len(v.illisibles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
