r"""Remet en fins de ligne LF les fichiers suivis dont la SEULE différence avec la version committée est le CRLF.

    tools\python\python.exe tools\normaliser_fins_de_ligne_datasets.py --plan    compte, n'écrit rien
    tools\python\python.exe tools\normaliser_fins_de_ligne_datasets.py           convertit

24/11/2026 -- POURQUOI. Les ~1,9 M manifestes de ``datasets/`` étaient sur le disque en CRLF alors que GitHub les a
en LF (contenu identique : 300/300 vérifiés). Git les voyait tous « modifiés » : chaque ``git status`` (Codex compris)
re-hachait 1,9 M fichiers (> 10 min), les ``git`` s'empilaient jusqu'à 19 et 11 Go, et le labo manquait de mémoire.

GARANTIE. Un fichier n'est réécrit QUE si ses octets, CRLF remplacés par LF, ont exactement l'empreinte git (blob
SHA-1) de l'index : on écrit alors la version committée elle-même, à l'octet près. Tout autre cas (contenu différent,
pas de CRLF, fichier absent, lien) est laissé tel quel et compté. Remplacement atomique (fichier temporaire puis
``os.replace``). Le rapport liste chaque fichier converti.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
RAPPORT = Path("runtime") / "reports" / "normalisation_fins_de_ligne_datasets.json"


def empreinte_blob(octets: bytes) -> str:
    """L'identifiant git (SHA-1) d'un blob de ces octets."""
    return hashlib.sha1(b"blob %d\0" % len(octets) + octets).hexdigest()


def entrees_suivies(root: Path, prefixe: str) -> list[tuple[str, str]]:
    """``(chemin, oid)`` des fichiers suivis sous ``prefixe`` (``git ls-files -s``, index seul, sans balayage)."""
    sortie = subprocess.run(["git", "ls-files", "-s", "-z", "--", prefixe], cwd=root, capture_output=True,
                            check=True).stdout
    entrees = []
    for brut in sortie.split(b"\0"):
        if not brut:
            continue
        tete, chemin = brut.split(b"\t", 1)
        mode, oid, stade = tete.split(b" ")
        if mode == b"100644" and stade == b"0":
            entrees.append((chemin.decode("utf-8"), oid.decode()))
    return entrees


def traiter(root: Path, chemin: str, oid: str, ecrire: bool) -> str:
    p = root / chemin
    try:
        if p.is_symlink() or not p.is_file():
            return "absent_ou_lien"
        octets = p.read_bytes()
    except OSError:
        return "illisible"
    if empreinte_blob(octets) == oid:
        return "deja_identique"
    if b"\r\n" not in octets:
        return "autre_difference_laisse"
    lf = octets.replace(b"\r\n", b"\n")
    if empreinte_blob(lf) != oid:
        return "autre_difference_laisse"
    if ecrire:
        tmp = p.with_name(f".{p.name}.{os.getpid()}.lf.tmp")
        try:
            tmp.write_bytes(lf)
            os.replace(tmp, p)
        except OSError:
            tmp.unlink(missing_ok=True)
            return "ecriture_impossible"
    return "converti"


def normaliser(root: Path, prefixe: str = "datasets/", ecrire: bool = True, ouvriers: int = 8,
               log=print) -> dict:
    t0 = time.time()
    entrees = entrees_suivies(root, prefixe)
    log(f"  {len(entrees):,} fichiers suivis sous {prefixe} ({time.time() - t0:.0f} s)")
    bilan: Counter = Counter()
    convertis: list[str] = []
    with ThreadPoolExecutor(max_workers=ouvriers) as pool:
        for n, ((chemin, _oid), etat) in enumerate(zip(entrees, pool.map(
                lambda e: traiter(root, e[0], e[1], ecrire), entrees, chunksize=256)), 1):
            bilan[etat] += 1
            if etat == "converti":
                convertis.append(chemin)
            if n % 100_000 == 0:
                log(f"    {n:,}/{len(entrees):,} ({time.time() - t0:.0f} s) {dict(bilan)}")
    return {"prefixe": prefixe, "ecrit": ecrire, "fichiers_suivis": len(entrees), "bilan": dict(bilan),
            "secondes": round(time.time() - t0, 1), "convertis": convertis,
            "regle": "reecrit seulement si CRLF->LF donne exactement le blob de l'index"}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--prefixe", default="datasets/")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--ouvriers", type=int, default=8)
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    r = normaliser(root, a.prefixe, ecrire=not a.plan, ouvriers=a.ouvriers)
    print(f"  bilan : {r['bilan']} en {r['secondes']} s", flush=True)
    if not a.plan:
        sortie = root / RAPPORT
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        print(f"  rapport : {RAPPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
