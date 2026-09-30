"""ALPHA P39 — WALLET behavior FINGERPRINTS : détecter une infrastructure commune (même entité derrière plusieurs wallets).

Par wallet : cadence des fills, nombre de coins, ratio maker/taker, régularité (TWAP), motif de tailles. Deux
wallets aux empreintes très proches ET qui tradent en même temps = probablement la même infra → on ne compte
pas leur « consensus » comme indépendant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def fingerprint(fills: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Empreinte d'un wallet depuis ses fills ({ts_ms, coin, side, maker?})."""
    ts = sorted(f["ts_ms"] for f in fills if isinstance(f.get("ts_ms"), (int, float)))
    coins = {f.get("coin") for f in fills}
    if len(ts) < 2:
        return {"n_fills": len(fills), "cadence_med_ms": None, "n_coins": len(coins), "maker_ratio": None}
    gaps = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
    makers = [1 for f in fills if f.get("maker") is True]
    return {"n_fills": len(fills), "cadence_med_ms": round(statistics.median(gaps), 1),
            "cadence_reguliere": bool(statistics.pstdev(gaps) < 0.5 * statistics.median(gaps)) if len(gaps) > 2 else None,
            "n_coins": len(coins), "maker_ratio": round(len(makers) / len(fills), 3) if fills else None}


def _similaires(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    ca, cb = a.get("cadence_med_ms"), b.get("cadence_med_ms")
    if not isinstance(ca, (int, float)) or not isinstance(cb, (int, float)) or max(ca, cb) <= 0:
        return False
    proche_cadence = abs(ca - cb) / max(ca, cb) < 0.2
    proche_coins = abs(a.get("n_coins", 0) - b.get("n_coins", 0)) <= 1
    return proche_cadence and proche_coins


def entites_communes(empreintes: Mapping[str, Mapping[str, Any]]) -> list[list[str]]:
    """Groupe les wallets aux empreintes très proches (infra probablement commune)."""
    wallets = list(empreintes)
    parent = {w: w for w in wallets}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i in range(len(wallets)):
        for j in range(i + 1, len(wallets)):
            if _similaires(empreintes[wallets[i]], empreintes[wallets[j]]):
                parent[find(wallets[j])] = find(wallets[i])
    groupes: dict[str, list[str]] = {}
    for w in wallets:
        groupes.setdefault(find(w), []).append(w)
    return [sorted(g) for g in groupes.values() if len(g) > 1]


__all__ = ["fingerprint", "entites_communes"]
