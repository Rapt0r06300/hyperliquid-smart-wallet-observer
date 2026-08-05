"""[AUD-162/164/165/166/178] Infrastructure d'experiences : registre SQLite PERSISTANT des essais,
recalcul DESCENDANT cible (invalidation transitive), map DETERMINISTE parallele (ordre d'entree
preserve), reduction HORS-MEMOIRE par morceaux (larger-than-RAM), et cache par NOEUD de DAG
(adressage par contenu). stdlib pure (sqlite3, threading, hashlib), 0 reseau, 0 ordre reel."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


class RegistreExperiencesSQLite:
    """Registre PERSISTANT des essais (params -> metriques) dans SQLite. Survit au redemarrage :
    rouvrir le meme fichier retrouve tous les essais. Idempotent par trial_id."""

    def __init__(self, chemin: str | Path) -> None:
        self.chemin = str(chemin)
        self._cx = sqlite3.connect(self.chemin)
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS essais "
            "(trial_id TEXT PRIMARY KEY, params TEXT, metriques TEXT)")
        self._cx.commit()

    def enregistrer(self, trial_id: str, params: Mapping, metriques: Mapping) -> None:
        self._cx.execute(
            "INSERT OR REPLACE INTO essais VALUES (?,?,?)",
            (str(trial_id), json.dumps(params, sort_keys=True), json.dumps(metriques, sort_keys=True)))
        self._cx.commit()

    def lire(self, trial_id: str) -> dict | None:
        row = self._cx.execute(
            "SELECT params, metriques FROM essais WHERE trial_id=?", (str(trial_id),)).fetchone()
        if row is None:
            return None
        return {"trial_id": str(trial_id), "params": json.loads(row[0]), "metriques": json.loads(row[1])}

    def compter(self) -> int:
        return int(self._cx.execute("SELECT COUNT(*) FROM essais").fetchone()[0])

    def fermer(self) -> None:
        self._cx.close()


def recompute_descendant(dependances: Mapping[str, Sequence[str]], noeud_change: str) -> list[str]:
    """Recalcul CIBLE : graphe {noeud: [dependances amont]}. Retourne les noeuds DESCENDANTS
    (transitifs) a recalculer quand `noeud_change` change -> on ne recalcule QUE l'aval touche."""
    avals: dict[str, list[str]] = {}
    for noeud, amonts in dependances.items():
        for a in amonts:
            avals.setdefault(a, []).append(noeud)
    a_recalculer: list[str] = []
    vus = set()
    pile = [noeud_change]
    while pile:
        cur = pile.pop()
        for suivant in avals.get(cur, []):
            if suivant not in vus:
                vus.add(suivant)
                a_recalculer.append(suivant)
                pile.append(suivant)
    return a_recalculer


def map_deterministe(fn: Callable, items: Sequence, *, workers: int = 4) -> list:
    """Parallelisme DETERMINISTE : fn en parallele mais RESULTATS dans l'ordre d'ENTREE (independant
    de l'ordre de fin). Meme entree -> meme sortie, toujours."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(fn, items))


def reduce_hors_memoire(morceaux: Iterable, reduce_fn: Callable, initial) -> dict:
    """Reduction LARGER-THAN-RAM : consomme les morceaux un a un (streaming paresseux), ne
    materialise jamais tout en memoire."""
    acc = initial
    n = 0
    for m in morceaux:
        acc = reduce_fn(acc, m)
        n += 1
    return {"resultat": acc, "morceaux_traites": n}


class CacheNoeudDag:
    """Cache par NOEUD de DAG, ADRESSE PAR CONTENU : cle = sha256(node_id + entrees). Un noeud dont
    les entrees n'ont pas change est servi du cache (pas de recalcul)."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._lock = threading.Lock()

    @staticmethod
    def cle(node_id: str, entrees) -> str:
        brut = json.dumps([node_id, entrees], sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(brut).hexdigest()

    def obtenir(self, node_id: str, entrees):
        with self._lock:
            return self._store.get(self.cle(node_id, entrees))

    def poser(self, node_id: str, entrees, valeur) -> None:
        with self._lock:
            self._store[self.cle(node_id, entrees)] = valeur
