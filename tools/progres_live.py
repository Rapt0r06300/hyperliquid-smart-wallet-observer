"""PROGRESSION LIVE PARTAGÉE (Flo 26/07, FX-2). Petit état thread-safe que le moteur met à jour PENDANT les
calculs (pas seulement en fin de cycle) et que le thread du dashboard lit en direct (même process). Sert à
remplir fait/total/pourcentage/vitesse/ETA/job/prochaine — plus JAMAIS des None décoratifs. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_ETAT = {"fait": 0, "total": 0, "job": None, "ensuite": None, "t0": None, "maj": None}


def reset(total: int = 0, *, job: str | None = None, ensuite: str | None = None):
    with _LOCK:
        _ETAT.update(fait=0, total=int(total), job=job, ensuite=ensuite, t0=time.time(), maj=time.time())


def publier(fait: int, total: int | None = None, *, job: str | None = None, ensuite: str | None = None):
    """Publie une progression. `total=None` conserve le total courant. Appelable très souvent (léger)."""
    with _LOCK:
        if _ETAT["t0"] is None:
            _ETAT["t0"] = time.time()
        _ETAT["fait"] = int(fait)
        if total is not None:
            _ETAT["total"] = int(total)
        if job is not None:
            _ETAT["job"] = job
        if ensuite is not None:
            _ETAT["ensuite"] = ensuite
        _ETAT["maj"] = time.time()


def lire() -> dict:
    """Rend fait/total/pourcentage/vitesse(items/s)/eta_s/job/ensuite calculés depuis les horodatages réels."""
    with _LOCK:
        e = dict(_ETAT)
    fait, total = e["fait"], e["total"]
    pct = round(100.0 * fait / total, 1) if total else None
    dt = (e["maj"] - e["t0"]) if (e["t0"] and e["maj"]) else 0.0
    vit = round(fait / dt, 2) if dt > 0 and fait > 0 else None
    eta = round((total - fait) / vit, 1) if (vit and vit > 0 and total and total > fait) else None
    return {"fait": fait, "total": total, "pourcentage": pct, "vitesse": vit, "eta": eta,
            "job": e["job"], "ensuite": e["ensuite"]}


__all__ = ["reset", "publier", "lire"]
