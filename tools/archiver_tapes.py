#!/usr/bin/env python3
"""Reset de session SANS perte : archive les tapes de `runtime/data` -> `runtime/archive/`.

Apres le depot dans le coffre certifie (sealer), on DEPLACE (jamais on ne supprime) toutes
les tapes `.jsonl` de `runtime/data` vers `runtime/archive/session_<horodate>/`. Resultat :
`runtime/data` repart vide (l'ecran affiche 0), et rien n'est perdu — tout est soit certifie
dans le coffre, soit archive brut. Les fichiers operationnels (verrous, PID, drapeaux, HTML,
etats .json) sont conserves en place. PAPER / lecture seule vis-a-vis du reseau.
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Fichiers .jsonl a NE PAS archiver (etats operationnels, pas des tapes de donnees).
GARDER = {
    "economic_collection_pids.jsonl",
}


def archiver(root: Path, *, now: datetime.datetime | None = None) -> dict:
    data = root / "runtime" / "data"
    if not data.is_dir():
        return {"deplaces": 0, "dest": None, "restants": 0}
    tapes = [p for p in sorted(data.glob("*.jsonl"))
             if p.is_file() and not p.is_symlink() and p.name not in GARDER]
    if not tapes:
        return {"deplaces": 0, "dest": None, "restants": 0}
    ts = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    dest = root / "runtime" / "archive" / f"session_{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    deplaces = 0
    restants = 0
    for p in tapes:
        cible = dest / p.name
        if cible.exists():               # collision horodate -> suffixe
            cible = dest / f"{p.stem}_{deplaces}{p.suffix}"
        try:
            shutil.move(str(p), str(cible))
            deplaces += 1
        except OSError:                  # fichier verrouille/ouvert -> on laisse en place
            restants += 1
    if deplaces == 0:
        try:
            dest.rmdir()
        except OSError:
            pass
        dest = None
    return {"deplaces": deplaces, "dest": str(dest) if dest else None, "restants": restants}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Archive les tapes runtime/data (reset de session sans perte).")
    p.add_argument("--root", default=str(RACINE))
    args = p.parse_args(argv)
    rap = archiver(Path(args.root))
    if rap["deplaces"]:
        print(f"[archive] {rap['deplaces']} tape(s) archivee(s) -> {rap['dest']} "
              f"(runtime/data repart a zero).", flush=True)
    else:
        print("[archive] aucune tape a archiver (runtime/data deja vide).", flush=True)
    if rap["restants"]:
        print(f"[archive] {rap['restants']} fichier(s) encore verrouilles, laisses en place.", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
