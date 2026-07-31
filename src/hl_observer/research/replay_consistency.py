"""ALPHA P9 — REPLAY = FORWARD : le même pipeline métier doit donner le MÊME résultat en replay et en forward.

Invariants testables : déterminisme (même intent+snapshot+config → même fill/PnL), stabilité de préfixe
(tronquer le futur ne change pas les décisions passées), robustesse aux doublons / out-of-order / carnet
périmé (ils sont filtrés, pas exploités). Ici les VÉRIFICATEURS ; le moteur reste `paper_engine` (causal).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def deterministe(resultats_run1: Sequence[Any], resultats_run2: Sequence[Any]) -> bool:
    """Même entrées → mêmes sorties (fills/PnL identiques)."""
    return list(resultats_run1) == list(resultats_run2)


def prefix_stable(decisions_complet: Sequence[Any], decisions_prefixe: Sequence[Any]) -> bool:
    """Tronquer le futur ne doit pas altérer les décisions passées."""
    k = len(decisions_prefixe)
    return list(decisions_complet[:k]) == list(decisions_prefixe)


def filtre_evenements(events: Sequence[dict], *, dernier_seq: int = -1, book_max_age_ms: float = 5000.0,
                      now_ms: float | None = None) -> dict[str, Any]:
    """Filtre doublons (seq déjà vue), out-of-order (seq < dernier), carnet périmé (âge > max). Rien d'exploité en douce."""
    gardes, rejets = [], {"doublon": 0, "out_of_order": 0, "stale": 0}
    vus: set[int] = set()
    d = dernier_seq
    for e in events:
        s = e.get("seq")
        if isinstance(s, (int, float)):
            if s in vus:
                rejets["doublon"] += 1
                continue
            if s < d:
                rejets["out_of_order"] += 1
                continue
            vus.add(s); d = max(d, s)
        if now_ms is not None and isinstance(e.get("book_ts_ms"), (int, float)):
            if now_ms - e["book_ts_ms"] > book_max_age_ms:
                rejets["stale"] += 1
                continue
        gardes.append(e)
    return {"gardes": gardes, "n_gardes": len(gardes), "rejets": rejets}


__all__ = ["deterministe", "prefix_stable", "filtre_evenements"]
