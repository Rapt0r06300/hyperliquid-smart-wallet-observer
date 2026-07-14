"""Pourquoi l'AST refuse-t-il ce fichier ? (2026-07-12)

L'audit de cablage a signale `tests/test_testnet_mode_controlled.py` comme ILLISIBLE.
Il a eu raison de refuser de conclure -- mais « illisible » n'est pas un diagnostic.
Cet outil dit CE QUI cloche, exactement, sans deviner.

    python tools/pourquoi_illisible.py [chemin...]

Sans argument : rescanne tout le depot et signale chaque fichier que l'AST rejette.
Lecture seule. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = ("__pycache__", "runtime/", "data/", ".git/", "node_modules/",
          "cli_pkg_DISABLED", "_archive", "logs/")


def _diagnostiquer(p: Path) -> str | None:
    brut = p.read_bytes()
    # `utf-8-sig` : c'est ce que fait Python lui-meme en lisant un `.py`. Decoder en `utf-8`
    # tout court laisse le BOM (U+FEFF) dans la chaine, et `ast.parse` s'etrangle dessus --
    # ce qui m'a fait accuser un fichier PARFAITEMENT valide (cf. `cablage._sans_bom`).
    txt = brut.decode("utf-8-sig", errors="ignore")
    try:
        ast.parse(txt)
    except SyntaxError as e:
        lignes = txt.splitlines()
        no = e.lineno or 0
        extrait = lignes[no - 1] if 0 < no <= len(lignes) else "(hors fichier)"
        return ("%s\n    SyntaxError : %s\n    ligne %s, col %s : %r\n"
                "    %d octets, %d lignes, BOM=%s"
                % (p.relative_to(ROOT).as_posix(), e.msg, no, e.offset, extrait,
                   len(brut), len(lignes), brut[:3] == b"\xef\xbb\xbf"))
    return None


def main(argv: list[str]) -> int:
    if argv:
        cibles = [ROOT / a for a in argv]
    else:
        cibles = [p for p in ROOT.rglob("*.py")
                  if not any(x in p.relative_to(ROOT).as_posix() for x in IGNORE)]

    casses = [d for p in cibles if (d := _diagnostiquer(p))]
    print("\n%d fichier(s) .py examine(s)" % len(cibles))
    if not casses:
        print("  aucun fichier illisible.\n")
        return 0
    print("  %d ILLISIBLE(S) :\n" % len(casses))
    for d in casses:
        print("  " + d + "\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
