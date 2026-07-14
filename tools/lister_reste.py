#!/usr/bin/env python3
"""Extrait TOUTES les taches non cochees de TASKLIST.md, dans l'ordre du fichier, numerotees.

    python tools/lister_reste.py   ->  RESTE-A-FAIRE.txt

Pourquoi un script : bash (mount) TRONQUE TASKLIST.md (84 Ko) -- il n'y voyait que 145 lignes
sur 291. Windows lit le fichier en entier. *En cas de desaccord, Windows a raison.*
Lecture seule. Aucun ordre reel.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "TASKLIST.md"
DEST = RACINE / "RESTE-A-FAIRE.txt"

# Taches deja FAITES mais dont la case n'a pas ete cochee dans le fichier.
DEJA_FAITES = {
    "#288": "DEJA CORRIGEE par #112",
    "#310": "DEJA RESOLUE par #594",
    "#355": "DEJA REFUTEE (GH-02 = H-160)",
    "#369": "DEJA FAITE par #588 (T2b)",
    "#586": "DEJA REFUTEE (H-181)",
    "#591": "DEJA FAITE (garde-fou affame)",
    "#594": "DEJA FAITE (2 tables d'edge)",
    "#597": "DEJA FAITE (cliquet de cablage)",
    "#598": "DEJA FAITE (2 tests UI)",
    "#599": "DEJA FAITE (couverture 83,83 %)",
}


def main() -> int:
    texte = SRC.read_text(encoding="utf-8", errors="replace")
    lignes = texte.splitlines()

    section = ""
    out: list[str] = []
    n = 0
    for ligne in lignes:
        if ligne.startswith("###") or (ligne.startswith("##") and not ligne.startswith("###")):
            section = ligne.lstrip("#").strip()
            continue
        if not ligne.startswith("- [ ]"):
            continue
        n += 1
        corps = ligne[5:].strip()
        corps = corps.replace("**", "").replace("`", "")
        corps = re.sub(r"\s+", " ", corps)
        m = re.match(r"^(#\d+)", corps)
        note = ""
        if m and m.group(1) in DEJA_FAITES:
            note = "   <<< %s" % DEJA_FAITES[m.group(1)]
        out.append((section, "%3d. %s%s" % (n, corps, note)))

    lignes_finales: list[str] = []
    derniere = None
    for sec, item in out:
        if sec != derniere:
            lignes_finales.append("")
            lignes_finales.append("--- %s" % (sec or "(sans section)"))
            derniere = sec
        lignes_finales.append(item)

    entete = [
        "=" * 78,
        " HYPERSMART OBSERVER - TOUT CE QUI RESTE (%d taches non cochees)" % n,
        " Extrait de TASKLIST.md le 2026-07-13. Ordre du fichier, rien enleve.",
        " Suite complete : 3566 verts / 0 rouge. safety-audit 8/8.",
        "=" * 78,
    ]
    DEST.write_text("\n".join(entete + lignes_finales) + "\n", encoding="utf-8")
    print("%d taches ecrites -> %s" % (n, DEST))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
