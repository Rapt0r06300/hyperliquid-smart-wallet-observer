"""Signal de QUALITÉ LEADER causal (#10) — track-record réalisé du leader (closedPnl).

POURQUOI
--------
Les leaders suivis sont une liste figée ; le labo ne cherchait pas *quels* leaders
maximisent le gain. Ici on dérive, pour chaque leader (``vault``), son **PnL réalisé
cumulé** (somme des ``closed_pnl`` de ses fills) connu à un instant donné. Un pré-filtre
GELABLE permet de ne copier qu'un leader dont le track-record prouvé dépasse un seuil.

INTÉGRITÉ (freeze-eligible)
---------------------------
- PUREMENT CAUSAL : au signal ``ts_ms``, on ne somme QUE les ``closed_pnl`` des fills du
  leader d'horodatage ``<= ts_ms`` (le PnL réalisé n'est connu qu'au moment de la clôture ;
  l'entrée qu'on copie n'est pas encore clôturée → jamais incluse). Aucune fuite look-ahead.
- Source = fills leaders matérialisés SAFE (``vault_fills.jsonl``). Prouvable → gelable.

Module PUR (parsing + préfixes cumulés + bisect) : testable sans réseau, sans état.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

#: sentinelle « filtre désactivé » : aucun leader n'a jamais un PnL < celui-ci.
SEUIL_LEADER_OFF_USD = -1e18


def _fini(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def build_leader_quality_index(
    fills: Sequence[Mapping[str, Any]] | None,
) -> dict[str, tuple[list[int], list[float]]]:
    """``{vault: ([ts_ms triés], [closed_pnl CUMULÉ])}``.

    Chaque entrée donne, à chaque horodatage de fill du leader, la somme de ses
    ``closed_pnl`` jusque-là (préfixe cumulé). Lignes sans vault/ts/closed_pnl valides
    ignorées. Les fills d'un même leader sont triés par ``ts_ms``.
    """
    tmp: dict[str, list[tuple[int, float]]] = {}
    for r in fills or ():
        if not isinstance(r, Mapping):
            continue
        vault = str(r.get("vault") or "")
        ts = r.get("ts_ms")
        cp = _fini(r.get("closed_pnl"))
        if (not vault or not isinstance(ts, int) or isinstance(ts, bool) or cp is None):
            continue
        tmp.setdefault(vault, []).append((int(ts), cp))
    index: dict[str, tuple[list[int], list[float]]] = {}
    for vault, pts in tmp.items():
        pts.sort(key=lambda p: p[0])
        ts_list: list[int] = []
        cum_list: list[float] = []
        cumul = 0.0
        for ts, cp in pts:
            cumul += cp
            ts_list.append(ts)
            cum_list.append(cumul)
        index[vault] = (ts_list, cum_list)
    return index


def leader_prior_pnl_at(
    index: Mapping[str, tuple[list[int], list[float]]], vault: Any, ts_ms: int,
) -> float | None:
    """PnL réalisé cumulé du leader au dernier fill ``<= ts_ms`` (causal strict).

    ``None`` si aucun fill causal (leader inconnu ou sans historique avant ``ts_ms``).
    """
    entry = index.get(str(vault or ""))
    if not entry:
        return None
    tss, cums = entry
    try:
        cible = int(ts_ms)
    except (TypeError, ValueError):
        return None
    i = bisect.bisect_right(tss, cible) - 1
    if i < 0:
        return None
    return cums[i]


def copie_leader_faible(
    index: Mapping[str, tuple[list[int], list[float]]], vault: Any, ts_ms: int,
    *, seuil_usd: float,
) -> bool:
    """``True`` si le track-record causal du leader est ``< seuil_usd`` → NE PAS copier.

    ``False`` en l'absence d'historique causal (fail-open : on ne bloque jamais sur une
    absence d'information, comme le filtre overshoot).
    """
    prior = leader_prior_pnl_at(index, vault, ts_ms)
    if prior is None:
        return False
    return prior < float(seuil_usd)


__all__ = [
    "SEUIL_LEADER_OFF_USD",
    "build_leader_quality_index",
    "leader_prior_pnl_at",
    "copie_leader_faible",
]
