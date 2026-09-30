"""Enregistreur de recherche generique (etapes 2/3/4/7) — brique de STOCKAGE sure et testee.

Ecrit des lignes jsonl horodatees, un fichier PAR-PROCESS (`<stream>.<pid>.jsonl`) pour eviter les
races entre process, avec un cap d'octets (troncature atomique tmp+replace). Lecture agregee via glob.

Cette brique ne fait qu'ECRIRE ce qu'on lui donne et RELIRE : aucun reseau, aucun ordre, aucune donnee
fabriquee. Elle servira a persister latence / funding / carnet L2 / prix lors d'un run de collecte
propre. Pur, local, paper-only.
"""
from __future__ import annotations

import glob
import json
import os
import time
from hl_observer.ops.echec_silencieux import noter as _noter_echec


def _path(base: str, stream: str) -> str:
    return os.path.join(base, f"{stream}.{os.getpid()}.jsonl")


def _cap(path: str, max_bytes: int) -> None:
    """Garde ~la seconde moitie du fichier (lignes entieres), ecriture atomique."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return
    keep = data[-(max_bytes // 2):]
    nl = keep.find(b"\n")
    if nl >= 0:
        keep = keep[nl + 1:]  # ne pas couper une ligne au milieu
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(keep)
    os.replace(tmp, path)


def record(base: str, stream: str, obj: dict, *, max_bytes: int = 50_000_000) -> str:
    """Ajoute une ligne jsonl (horodatee `_ts`) au fichier par-process du flux. Retourne le chemin."""
    os.makedirs(base, exist_ok=True)
    path = _path(base, stream)
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            _cap(path, max_bytes)
    except OSError:
        _noter_echec("hl_observer/collection/research_recorder.py:47")
    row = dict(obj)
    row.setdefault("_ts", time.time())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # BUG CORRIGE (audit 2026-07-11) : le cap n'etait verifie qu'AVANT l'ecriture, donc le fichier
    # au repos pouvait depasser max_bytes d'une ligne (mesure : 20005 > 20000). On refait respecter
    # la borne APRES l'append : le fichier sur disque est TOUJOURS <= max_bytes.
    try:
        if os.path.getsize(path) > max_bytes:
            _cap(path, max_bytes)
    except OSError:
        _noter_echec("hl_observer/collection/research_recorder.py:59")
    return path


def read_stream(base: str, stream: str) -> list:
    """Relit et agrege tous les fichiers par-process d'un flux (ordre stable par nom)."""
    out = []
    for fp in sorted(glob.glob(os.path.join(base, f"{stream}.*.jsonl"))):
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            _noter_echec("hl_observer/collection/research_recorder.py:75")
        except OSError:
            _noter_echec("hl_observer/collection/research_recorder.py:77")
    return out
