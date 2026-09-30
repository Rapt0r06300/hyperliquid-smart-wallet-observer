"""ALPHA P56 / FIX-04 — FACTORY parallèle : workers READ-ONLY, UN seul writer, DÉTERMINISME strict.

Les workers calculent des trials en lecture seule ; un seul writer fusionne dans le registre. La fusion est
DÉTERMINISTE et vérifie le CONTENU, pas seulement les IDs :
  * dédup par empreinte de contenu complète ;
  * **conflit = même `trial_id` mais CONTENU différent → ERROR** (signale un non-déterminisme entre workers) ;
  * tri stable → résultat identique quel que soit l'ordre/nombre de workers (1/2/N).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def _cle(row: Mapping[str, Any]) -> str:
    return str(row.get("trial_id") or row.get("config_hash") or row.get("idea"))


def _empreinte(row: Mapping[str, Any]) -> str:
    return hashlib.sha1(json.dumps(dict(row), sort_keys=True, default=str).encode("utf-8")).hexdigest()


def merge_deterministe(resultats_workers: Sequence[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Fusionne les trials de plusieurs workers. Dédup par contenu ; conflit id+contenu différent = ValueError."""
    par_cle: dict[str, tuple[str, dict[str, Any]]] = {}
    for worker in resultats_workers:
        for row in worker:
            cle = _cle(row)
            emp = _empreinte(row)
            if cle in par_cle:
                if par_cle[cle][0] != emp:
                    raise ValueError(
                        "CONFLIT parallel factory : trial_id %r présent avec DEUX contenus différents "
                        "(non-déterminisme entre workers)" % cle)
                # même id + même contenu -> déjà pris, on ignore
            else:
                par_cle[cle] = (emp, dict(row))
    return [par_cle[k][1] for k in sorted(par_cle)]


def resultat_invariant(merge_a: Sequence[Mapping[str, Any]], merge_b: Sequence[Mapping[str, Any]]) -> bool:
    """Deux fusions sont invariantes si leur CONTENU complet (pas seulement les IDs) est identique, ordre inclus."""
    return [_empreinte(r) for r in merge_a] == [_empreinte(r) for r in merge_b]


def sharder(items: Sequence[Any], n_shards: int) -> list[list[Any]]:
    """Répartit les items en `n_shards` groupes contigus stables (même découpe pour un même n)."""
    n_shards = max(1, int(n_shards))
    return [list(items[i::n_shards]) for i in range(n_shards)]


def executer_parallele(items: Sequence[Any], worker_fn: Callable[[Sequence[Any]], Sequence[Mapping[str, Any]]], *,
                       n_workers: int = 4, parallele: bool = True) -> list[dict[str, Any]]:
    """Découpe `items` en shards READ-ONLY, exécute `worker_fn(shard)` (threads si `parallele`), puis FUSIONNE
    de façon déterministe. Le nombre de workers ne change JAMAIS le résultat (merge trié + anti-conflit).

    L'executor est résolu via ``concurrent.futures`` au moment de l'appel. Cela conserve exactement
    le comportement production tout en permettant aux harness offline/coverage de substituer un executor
    déterministe sans laisser partir de vrais threads alimentés par des callables synthétiques.
    """
    shards = sharder(items, n_workers)
    if parallele and n_workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            resultats = list(ex.map(worker_fn, shards))
    else:
        resultats = [worker_fn(s) for s in shards]
    return merge_deterministe(resultats)


def prouver_puis_executer(items: Sequence[Any], worker_fn: Callable[[Sequence[Any]], Sequence[Mapping[str, Any]]],
                          *, n_workers: int = 4) -> dict[str, Any]:
    """Parallélisation SEULEMENT après déterminisme prouvé : calcule le résultat séquentiel (référence) ET le
    résultat à `n_workers`, vérifie l'invariance. Si invariant → on garde le parallèle ; sinon → repli séquentiel
    (on ne fait JAMAIS confiance à un parallélisme non déterministe). Un conflit id/contenu = non déterministe."""
    sequentiel = executer_parallele(items, worker_fn, n_workers=1, parallele=False)
    try:
        parallele = executer_parallele(items, worker_fn, n_workers=n_workers, parallele=True)
        invariant = resultat_invariant(sequentiel, parallele)
    except ValueError:
        invariant = False
    return {"parallelise": invariant, "resultat": (parallele if invariant else sequentiel),
            "n_workers": (n_workers if invariant else 1),
            "raison": (None if invariant else "non-déterminisme détecté entre workers → repli séquentiel")}


def benchmark(items: Sequence[Any], worker_fn: Callable[[Sequence[Any]], Sequence[Mapping[str, Any]]], *,
              n_workers: int = 4) -> dict[str, Any]:
    """Mesure RÉELLE temps + pic mémoire (tracemalloc) du séquentiel vs parallèle, et l'invariance. Aucune
    promesse de speedup : on rapporte les vrais chiffres (le GIL peut annuler le gain sur du CPU-bound Python)."""
    tracemalloc.start()
    t0 = time.perf_counter()
    seq = executer_parallele(items, worker_fn, n_workers=1, parallele=False)
    seq_ms = (time.perf_counter() - t0) * 1e3
    seq_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.reset_peak()
    t1 = time.perf_counter()
    par = executer_parallele(items, worker_fn, n_workers=n_workers, parallele=True)
    par_ms = (time.perf_counter() - t1) * 1e3
    par_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"n_items": len(items), "n_workers": n_workers,
            "seq_ms": round(seq_ms, 3), "par_ms": round(par_ms, 3),
            "seq_peak_kb": round(seq_peak / 1024, 1), "par_peak_kb": round(par_peak / 1024, 1),
            "speedup": (round(seq_ms / par_ms, 3) if par_ms > 0 else None),
            "invariant": resultat_invariant(seq, par)}


__all__ = ["merge_deterministe", "resultat_invariant", "sharder", "executer_parallele",
           "prouver_puis_executer", "benchmark"]
