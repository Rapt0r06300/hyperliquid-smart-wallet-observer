"""Performance & scalabilité — pur, testé. Exécution du backlog :
LRUCache (IMPROVE-27, cache des chemins de prix), bounded_parallel_map (IMPROVE-29, parallélisme
borné anti-ban), profile_call (IMPROVE-26, profiler), create_sqlite_indexes (IMPROVE-30),
load_test (IMPROVE-25, test de charge). Aucun ordre.
"""
from __future__ import annotations

import cProfile
import io
import pstats
import sqlite3
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor


class LRUCache:
    """Cache LRU borné (évite de recharger les chemins de prix à chaque backtest)."""

    def __init__(self, capacity: int = 128):
        self.capacity = max(1, int(capacity))
        self._d = OrderedDict()

    def get(self, key):
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key]

    def put(self, key, value) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        if len(self._d) > self.capacity:
            self._d.popitem(last=False)      # évince le plus ancien

    def __len__(self) -> int:
        return len(self._d)


def bounded_parallel_map(fn, items, *, workers: int = 4) -> list:
    """Map parallèle BORNÉ (jamais de saturation / de ban)."""
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        return list(ex.map(fn, items))


def profile_call(fn, *args, **kwargs) -> dict:
    """Profile un appel : durée + top fonctions coûteuses (trouver les vrais goulots).

    BUG CORRIGÉ (fuzzing de l'audit, 2026-07-11) : si `fn` levait une exception, `pr.disable()`
    n'était JAMAIS appelé -> le profileur restait installé dans l'interpréteur et TOUS les appels
    suivants échouaient ("Cannot install a profile function while another profile function is
    being installed"). Sur un run de 48 h, ça empoisonne le processus entier. Le `finally`
    garantit désormais la désinstallation, quoi qu'il arrive.
    """
    t0 = time.perf_counter()
    pr = cProfile.Profile()
    pr.enable()
    try:
        res = fn(*args, **kwargs)
    finally:
        pr.disable()                    # TOUJOURS desinstaller, meme si fn() a plante
    dur = time.perf_counter() - t0
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(5)
    return {"result": res, "seconds": dur, "profile": s.getvalue()[:2000]}


def create_sqlite_indexes(db_path: str, table: str, columns) -> list:
    """Crée les index sur les colonnes les plus interrogées (accélère les lectures)."""
    con = sqlite3.connect(db_path)
    try:
        made = []
        for c in columns:
            name = f"idx_{table}_{c}"
            con.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({c})")
            made.append(name)
        con.commit()
        return made
    finally:
        con.close()


def load_test(fn, *, n: int = 1000) -> dict:
    """Test de charge : exécute fn n fois, compte les erreurs et mesure. Le bot doit tenir."""
    t0 = time.perf_counter()
    errors = 0
    for i in range(int(n)):
        try:
            fn(i)
        except Exception:
            errors += 1
    return {"runs": int(n), "errors": errors, "seconds": round(time.perf_counter() - t0, 4)}
