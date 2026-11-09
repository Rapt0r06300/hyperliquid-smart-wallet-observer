"""Signal d'OVERSHOOT causal dérivé du contexte SAFE (asset_ctx : mark vs oracle).

POURQUOI
--------
Un *overshoot* = le prix ``mark`` s'écarte fortement de l'``oracle`` (pression de
liquidation / débordement). Copier un leader EN PLEIN débordement est risqué : le prix
revient souvent vers l'oracle (fade), donc l'entrée copiée se ferait à mauvais prix.
Ce module fournit un **filtre anti-copie** : quand |overshoot| dépasse un seuil, on ne
copie pas (on laisse passer le débordement).

INTÉGRITÉ (freeze-eligible)
---------------------------
- PUREMENT CAUSAL : à l'instant ``ts_ms`` d'une entrée, on ne lit QUE le dernier snapshot
  d'horodatage ``<= ts_ms`` (jamais de futur, aucune fuite look-ahead).
- Le ``mark`` et l'``oracle`` viennent du corpus **SAFE** (famille
  ``copy_vault_active_asset_ctx``) → une stratégie qui s'en sert reste *prouvable* et donc
  gelable. Aucune donnée LOCAL non prouvée n'est utilisée ici.

Module PUR (parsing + bisect) : testable sans réseau, sans état.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

#: valeur hors de laquelle on considère que mark/oracle sont absurdes (bps). Garde-fou.
OVERSHOOT_BPS_PLAUSIBLE_MAX = 100_000.0


def _fini(x: Any) -> float | None:
    """Flottant fini, sinon None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def build_overshoot_index(
    asset_ctx_rows: Sequence[Mapping[str, Any]] | None,
) -> dict[str, tuple[list[int], list[float]]]:
    """Construit un index causal ``{coin: ([ts_ms triés], [overshoot_bps])}``.

    ``overshoot_bps = (mark - oracle) / oracle * 1e4`` (signe conservé : positif = mark
    au-dessus de l'oracle). Les lignes sans coin/ts/mark/oracle valides sont ignorées.
    """
    tmp: dict[str, list[tuple[int, float]]] = {}
    for r in asset_ctx_rows or ():
        if not isinstance(r, Mapping):
            continue
        coin = str(r.get("coin") or "").upper()
        ts = r.get("ts_ms")
        mark = _fini(r.get("mark"))
        oracle = _fini(r.get("oracle"))
        if (not coin or not isinstance(ts, int) or isinstance(ts, bool)
                or mark is None or oracle is None or oracle <= 0):
            continue
        ov = (mark - oracle) / oracle * 1e4
        if abs(ov) > OVERSHOOT_BPS_PLAUSIBLE_MAX:
            continue  # mark/oracle incohérents -> on n'invente pas de signal
        tmp.setdefault(coin, []).append((int(ts), ov))
    index: dict[str, tuple[list[int], list[float]]] = {}
    for coin, pts in tmp.items():
        pts.sort(key=lambda p: p[0])
        index[coin] = ([p[0] for p in pts], [p[1] for p in pts])
    return index


def overshoot_bps_at(
    index: Mapping[str, tuple[list[int], list[float]]], coin: Any, ts_ms: int,
) -> float | None:
    """Overshoot (bps, signé) au dernier snapshot ``<= ts_ms`` pour ``coin``.

    CAUSAL STRICT : ne renvoie jamais un snapshot de ``ts > ts_ms``. ``None`` si aucun
    snapshot causal disponible pour ce coin.
    """
    entry = index.get(str(coin or "").upper())
    if not entry:
        return None
    tss, ovs = entry
    try:
        cible = int(ts_ms)
    except (TypeError, ValueError):
        return None
    i = bisect.bisect_right(tss, cible) - 1
    if i < 0:
        return None
    return ovs[i]


def copie_bloquee(
    index: Mapping[str, tuple[list[int], list[float]]], coin: Any, ts_ms: int,
    *, seuil_bps: float,
) -> bool:
    """``True`` si |overshoot causal| dépasse ``seuil_bps`` → NE PAS copier (débordement).

    ``False`` quand il n'y a pas de signal causal (on ne bloque jamais sur une absence
    d'information : fail-open côté filtre, l'intégrité économique reste jugée par ailleurs).
    """
    ov = overshoot_bps_at(index, coin, ts_ms)
    if ov is None:
        return False
    return abs(ov) > float(seuil_bps)


__all__ = [
    "OVERSHOOT_BPS_PLAUSIBLE_MAX",
    "build_overshoot_index",
    "overshoot_bps_at",
    "copie_bloquee",
]
