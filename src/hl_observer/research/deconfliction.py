"""ALPHA P36 — DÉCONFLICTION des signaux : wallet+TWAP+OFI+Binance shock simultanés = 1 épisode économique.

Sans déconfliction, un même mouvement compté par 4 détecteurs = quadruple comptage → LCB/PF gonflés. On
regroupe les signaux proches (même coin, fenêtre courte) sous un `event_cluster_id` unique : une seule
opportunité économique. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def deconflicter(signaux: Sequence[Mapping[str, Any]], *, fenetre_ms: int = 1000) -> dict[str, Any]:
    """Assigne un event_cluster_id : signaux du MÊME coin à < fenetre_ms = 1 épisode. Retourne signaux + n_clusters."""
    ordonnes = sorted(
        (dict(s) for s in signaux if s.get("coin") is not None and isinstance(s.get("ts_ms"), (int, float))),
        key=lambda s: (str(s["coin"]), float(s["ts_ms"])))
    out: list[dict[str, Any]] = []
    dernier: dict[str, tuple[str, float]] = {}
    compteur = 0
    for s in ordonnes:
        coin = str(s["coin"])
        t = float(s["ts_ms"])
        prev = dernier.get(coin)
        if prev is None or (t - prev[1]) > fenetre_ms:
            compteur += 1
            cid = "%s#%d" % (coin, compteur)
        else:
            cid = prev[0]
        s["event_cluster_id"] = cid
        dernier[coin] = (cid, t)
        out.append(s)
    n_clusters = len({s["event_cluster_id"] for s in out})
    return {"signaux": out, "n_signaux": len(out), "n_clusters": n_clusters,
            "facteur_sur_comptage": round(len(out) / n_clusters, 3) if n_clusters else None}


def types_par_cluster(signaux_deconflictes: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Pour chaque épisode, la liste des types de signaux qui l'ont déclenché (wallet/twap/ofi/binance...)."""
    d: dict[str, list[str]] = {}
    for s in signaux_deconflictes:
        d.setdefault(str(s.get("event_cluster_id")), []).append(str(s.get("type", "?")))
    return d


__all__ = ["deconflicter", "types_par_cluster"]
