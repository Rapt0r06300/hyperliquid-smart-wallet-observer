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
import hashlib
import json
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.datasets.coffre_certifie import motif_non_certifie  # noqa: E402

ETAT_COFFRE = Path("runtime") / "coffre_certifie" / "SOURCES_TRAITEES.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for bloc in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _etat_coffre(root: Path) -> dict:
    try:
        etat = json.loads((root / ETAT_COFFRE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return etat if isinstance(etat, dict) else {}


def passe_par_le_certificateur(root: Path, tape: Path, etat: dict) -> tuple[bool, str]:
    """Ce ruban peut-il quitter ``runtime/data`` ? Seulement s'il est passé par le certificateur.

    * écarté PAR CONCEPTION (inférence, dérivé, diagnostic...) : le certificateur l'a recensé
      avec son motif, il peut être archivé ;
    * certifié : l'état du coffre connaît ce chemin avec EXACTEMENT ce contenu (même SHA-256) ;
    * sinon — jamais certifié, modifié depuis, ou flux inconnu du certificateur — il RESTE en
      place : le déplacer le ferait sortir du champ de la certification sans jamais y être passé.
    """
    motif = motif_non_certifie(tape.name)
    if motif is not None:
        return True, f"ecarte_par_conception:{motif[0]}"
    try:
        relatif = tape.relative_to(root)
    except ValueError:
        return False, "hors_du_projet"
    entree = etat.get(str(relatif)) or etat.get(relatif.as_posix())
    if not isinstance(entree, dict) or not entree.get("sha256"):
        return False, "jamais_certifie"
    if entree["sha256"] != _sha256(tape):
        return False, "modifie_depuis_la_certification"
    return True, "certifie"

# Fichiers .jsonl a NE PAS archiver (etats operationnels, pas des tapes de donnees).
GARDER = {
    "economic_collection_pids.jsonl",
}


def archiver(root: Path, *, now: datetime.datetime | None = None) -> dict:
    root = Path(root).resolve()
    data = root / "runtime" / "data"
    if not data.is_dir():
        return {"deplaces": 0, "dest": None, "restants": 0, "retenus": []}
    candidats = [p for p in sorted(data.glob("*.jsonl"))
                 if p.is_file() and not p.is_symlink() and p.name not in GARDER]
    # RÈGLE : aucun ruban ne sort de runtime/data sans être passé par le certificateur.
    etat = _etat_coffre(root)
    tapes: list[Path] = []
    retenus: list[dict] = []
    for p in candidats:
        if p.stat().st_size == 0:
            tapes.append(p)                       # ruban vide : rien à certifier
            continue
        autorise, raison = passe_par_le_certificateur(root, p, etat)
        if autorise:
            tapes.append(p)
        else:
            retenus.append({"fichier": p.name, "raison": raison})
    if not tapes:
        return {"deplaces": 0, "dest": None, "restants": 0, "retenus": retenus}
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
    return {"deplaces": deplaces, "dest": str(dest) if dest else None, "restants": restants,
            "retenus": retenus}


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
    if rap["retenus"]:
        print(f"[archive] {len(rap['retenus'])} ruban(s) LAISSES EN PLACE : pas encore passes par le "
              f"certificateur (ils seront certifies au prochain passage, puis archives) :", flush=True)
        for ligne in rap["retenus"]:
            print(f"   - {ligne['fichier']} : {ligne['raison']}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
