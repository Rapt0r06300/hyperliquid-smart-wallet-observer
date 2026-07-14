"""AUCUN .cmd NE DOIT CONTENIR UN OCTET NON-ASCII (garde permanent, 2026-07-12).

POURQUOI CE GARDE EXISTE
------------------------
Ce bug est revenu TROIS FOIS :
  1. MOISSONNER-GITHUB.cmd -> "'ISSONNEUR' n'est pas reconnu"
  2. MOISSONNER-GITHUB.cmd -> cmd executait les commentaires REM
  3. MEGATEST.cmd          -> "'5001' n'est pas reconnu" en boucle
                              (c'est "chcp 65001" ampute de son 6)

LE MECANISME
------------
Avec `chcp 65001`, cmd.exe lit le fichier .cmd octet par octet mais DECALE son
analyseur sur les sequences UTF-8 multi-octets. Il perd des octets. Une ligne
`chcp 65001 >nul` devient `...5001 >nul` -> cmd tente d'EXECUTER "5001".
Pire : un `REM` peut sauter, et cmd EXECUTE alors le commentaire.

Un seul tiret cadratin, un seul point median, un seul accent suffit.

LA REGLE
--------
    Un fichier .cmd doit etre en ASCII PUR. Sans exception.
    Les accents et la ponctuation typographique vont dans les .py et les .md,
    jamais dans un .cmd.

Ce module ne fait que LIRE des fichiers. Aucun ordre, aucun reseau.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["scanner_cmd", "MOTIF_DANGEREUX"]

# Le combo mortel : un octet non-ASCII ET un `chcp` actif dans le meme fichier.
# Sans chcp, un non-ASCII n'affiche qu'un mojibake (moche, pas fatal).
# Avec chcp 65001, il DECALE l'analyseur -> cmd execute n'importe quoi.
MOTIF_DANGEREUX = "non-ASCII + chcp"


def _lignes_non_ascii(chemin: Path) -> list[tuple[int, str, str]]:
    """Rend [(no_ligne, extrait, les caracteres fautifs)] -- lecture en octets bruts."""
    out: list[tuple[int, str, str]] = []
    try:
        brut = chemin.read_bytes()
    except OSError:
        return out
    for i, ligne_b in enumerate(brut.split(b"\n"), start=1):
        fautifs = sorted({bytes([b]) for b in ligne_b if b > 0x7F})
        if not fautifs:
            continue
        texte = ligne_b.decode("utf-8", errors="replace").rstrip("\r")
        chars = ligne_b.decode("utf-8", errors="replace")
        mauvais = "".join(sorted({c for c in chars if ord(c) > 0x7F}))
        out.append((i, texte.strip()[:70], mauvais))
    return out


def _a_un_chcp(chemin: Path) -> bool:
    """Un `chcp` REELLEMENT execute (pas une simple mention dans un REM)."""
    try:
        for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
            nu = ligne.strip().lstrip("@").strip()
            if nu.lower().startswith("rem "):
                continue
            if nu.lower().startswith("chcp"):
                return True
    except OSError:
        pass
    return False


def scanner_cmd(racine: str | Path = ".") -> dict:
    """Scanne tous les .cmd. Rend un rapport ; ne modifie RIEN.

    `casses`   : non-ASCII ET chcp actif -> cmd va executer n'importe quoi. BLOQUANT.
    `a_risque` : non-ASCII sans chcp     -> mojibake, pas fatal, mais a nettoyer.
    """
    racine = Path(racine)
    casses, a_risque, propres = [], [], []
    for chemin in sorted(racine.rglob("*.cmd")):
        if any(p in {".git", "node_modules", "runtime"} for p in chemin.parts):
            continue
        mauvaises = _lignes_non_ascii(chemin)
        rel = str(chemin.relative_to(racine))
        if not mauvaises:
            propres.append(rel)
            continue
        entree = {
            "fichier": rel,
            "n_lignes": len(mauvaises),
            "exemples": [
                {"ligne": n, "caracteres": c, "extrait": t} for n, t, c in mauvaises[:3]
            ],
        }
        (casses if _a_un_chcp(chemin) else a_risque).append(entree)
    return {
        "casses": casses,
        "a_risque": a_risque,
        "propres": propres,
        "verdict": "ECHEC" if casses else "OK",
        "regle": (
            "Un .cmd doit etre en ASCII PUR. Avec chcp 65001, un octet non-ASCII decale "
            "l'analyseur de cmd.exe : il perd des octets, saute des REM, et EXECUTE les "
            "commentaires. Bug rencontre 3 fois (2026-07-12)."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    racine = argv[0] if argv else "."
    rap = scanner_cmd(racine)

    print("=" * 78)
    print("  GARDE ASCII DES .cmd -- un octet non-ASCII fait executer les commentaires")
    print("=" * 78)
    print(f"  propres  : {len(rap['propres'])}")
    print(f"  a risque : {len(rap['a_risque'])}  (non-ASCII, mais pas de chcp -> mojibake seulement)")
    print(f"  CASSES   : {len(rap['casses'])}  (non-ASCII + chcp -> cmd execute n'importe quoi)")
    print()

    for e in rap["casses"]:
        print(f"  [CASSE]   {e['fichier']}  ({e['n_lignes']} lignes non-ASCII, chcp ACTIF)")
        for ex in e["exemples"]:
            print(f"              l.{ex['ligne']:<4} {ex['caracteres']!r}  {ex['extrait']}")
    for e in rap["a_risque"]:
        print(f"  [a risque] {e['fichier']}  ({e['n_lignes']} lignes non-ASCII, pas de chcp)")

    print()
    if rap["casses"]:
        print("  ECHEC : ces .cmd vont faire executer leurs propres commentaires par cmd.exe.")
        print("  Correctif : reecrire le fichier en ASCII PUR (pas de tiret cadratin, pas de")
        print("  point median, pas d'accent). PYTHONIOENCODING + PYTHONUTF8 suffisent : pas de chcp.")
        return 1
    print("  OK : aucun .cmd ne peut faire executer ses commentaires.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
