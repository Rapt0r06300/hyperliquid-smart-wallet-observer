"""ALPHA Q — lecture JSONL en STREAMING (générateur), comptage mmap, et cache par IDENTITÉ de fichier.

But FIX-53 : plus de relecture complète du JSONL par trial. On lit en flux (jamais toute la liste en mémoire),
on compte les lignes via mmap (sans décoder le JSON), et un `CacheParFichier` mémorise un dérivé par
(chemin, transformation) tant que l'empreinte du fichier (taille + mtime) ne change pas — sinon il RECALCULE
(invalidation honnête). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
import mmap
import os
from collections.abc import Callable, Iterator
from typing import Any


def stream_jsonl(path: str, *, max_lignes: int | None = None) -> Iterator[dict[str, Any]]:
    """Générateur : rend chaque enregistrement JSON un par un (jamais toute la liste en RAM). Ignore les lignes
    vides ou malformées (jamais exploitées en douce)."""
    n = 0
    with open(path, encoding="utf-8") as f:
        for ligne in f:
            if max_lignes is not None and n >= max_lignes:
                return
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                obj = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            n += 1
            yield obj


def reduce_stream(path: str, fn: Callable[[Any, dict[str, Any]], Any], init: Any, *,
                  max_lignes: int | None = None) -> Any:
    """Replie le flux sans jamais le matérialiser : `acc = fn(acc, record)` sur chaque enregistrement."""
    acc = init
    for rec in stream_jsonl(path, max_lignes=max_lignes):
        acc = fn(acc, rec)
    return acc


def compter_lignes(path: str) -> int:
    """Compte les lignes NON vides via mmap (scan C, sans décoder le JSON ni charger le fichier en liste)."""
    with open(path, "rb") as f:
        taille = os.fstat(f.fileno()).st_size
        if taille == 0:
            return 0
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            nl, pos = 0, 0
            while True:
                j = mm.find(b"\n", pos)
                if j == -1:
                    break
                nl += 1
                pos = j + 1
            fin_par_nl = mm[taille - 1:taille] == b"\n"
    return nl + (0 if fin_par_nl else 1)      # dernière ligne sans \n terminal = 1 enregistrement de plus


def empreinte_fichier(path: str) -> tuple[int, int] | None:
    """(taille, mtime_ns) — change dès que le fichier est modifié ; None s'il n'existe pas."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


class CacheParFichier:
    """Mémorise un dérivé par (chemin, transformation) tant que l'empreinte du fichier ne bouge pas. Un fichier
    modifié (taille/mtime) invalide l'entrée et force le recalcul — jamais une valeur périmée servie en douce."""

    def __init__(self) -> None:
        self._c: dict[tuple[str, str], tuple[tuple[int, int], Any]] = {}
        self.hits = 0
        self.miss = 0
        self.invalidations = 0

    def obtenir(self, path: str, transformation: str, calcul: Callable[[], Any]) -> Any:
        emp = empreinte_fichier(path)
        cle = (path, transformation)
        cache = self._c.get(cle)
        if cache is not None and emp is not None and cache[0] == emp:
            self.hits += 1
            return cache[1]
        if cache is not None:
            self.invalidations += 1        # empreinte différente (fichier modifié) -> on recalcule
        self.miss += 1
        val = calcul()
        if emp is not None:
            self._c[cle] = (emp, val)
        return val


__all__ = ["stream_jsonl", "reduce_stream", "compter_lignes", "empreinte_fichier", "CacheParFichier"]
