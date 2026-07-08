"""Sélection RÉELLE du grinder sur le tableau d'opportunités unifié (profondeur B).

Au lieu de laisser chaque stratégie (copy/funding/arbitrage) remplir des slots
indépendamment (silos), on classe les ordres d'ENTRÉE générés par le power score
du tableau unifié et on ne garde que les K meilleurs globalement. Les SORTIES
(CLOSE) ne sont JAMAIS filtrées — supprimer un exit = garder une position perdante.

Flag-gated (HYPERSMART_GRINDER_UNIFIED_SELECTION), no-op par défaut → aucune
régression tant que non activé + validé en replay A/B. Pur, paper-only.
"""

from __future__ import annotations

import os
from typing import Any

from hl_observer.integration.opportunity_board_adapter import board_from_fusion_result
from hl_observer.signals.unified_opportunity_board import BoardEntry


def _g(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_exit(order: Any) -> bool:
    action = str(_g(order, "action", "OPEN") or "").upper()
    otype = str(_g(order, "order_type", "") or "").upper()
    return action == "CLOSE" or "CLOSE" in otype


def select_orders_by_board(
    orders: list[Any],
    board: list[BoardEntry] | list[dict],
    *,
    max_new_entries: int | None = None,
    require_board_match: bool = False,
) -> list[Any]:
    """Garde tous les exits ; classe les entrées par power du board, cape aux K meilleures.

    require_board_match=True → une entrée dont le coin n'est PAS dans le board est
    abandonnée (le board est la source de vérité). Défaut False = classe/cape sans
    abandon dur (plus sûr).
    """
    by_coin: dict[str, float] = {}
    for e in board or ():
        coin = str(_g(e, "coin", "") or "").upper()
        if not coin:
            continue
        by_coin[coin] = max(by_coin.get(coin, 0.0), float(_g(e, "power_score", 0.0) or 0.0))

    exits: list[Any] = []
    opens: list[Any] = []
    for o in orders or ():
        (exits if _is_exit(o) else opens).append(o)

    def score(o: Any) -> float | None:
        return by_coin.get(str(_g(o, "coin", "") or "").upper())

    opens_ranked = sorted(opens, key=lambda o: -(score(o) or 0.0))
    kept: list[Any] = []
    for o in opens_ranked:
        if max_new_entries is not None and len(kept) >= int(max_new_entries):
            break
        if require_board_match and score(o) is None:
            continue
        kept.append(o)
    return exits + kept


def maybe_select_by_unified_board(
    orders: list[Any],
    *,
    funding_signals: Any = (),
    triangular: Any = (),
    distilled_opportunities: Any = (),
    now_ms: int = 0,
    env: dict | None = None,
) -> list[Any]:
    """Hook 1-ligne pour le fusion runtime. No-op sauf si le flag est actif.
    Construit le board depuis les candidats locaux puis filtre les ordres."""
    e = env if env is not None else os.environ
    if str(e.get("HYPERSMART_GRINDER_UNIFIED_SELECTION", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return orders
    try:
        cap_raw = e.get("HYPERSMART_GRINDER_MAX_NEW_ENTRIES")
        cap = int(cap_raw) if cap_raw not in (None, "") else None
        strict = str(e.get("HYPERSMART_GRINDER_REQUIRE_BOARD_MATCH", "0")).strip().lower() in {"1", "true", "yes", "on"}

        class _R:  # objet compatible pour l'adaptateur
            pass
        r = _R()
        r.funding_signals = list(funding_signals or ())
        r.triangular_opportunities = list(triangular or ())
        r.distilled_opportunity_report = type("D", (), {"opportunities": list(distilled_opportunities or ())})()
        board = board_from_fusion_result(r, now_ms=now_ms, limit=64)
        return select_orders_by_board(orders, board, max_new_entries=cap, require_board_match=strict)
    except Exception:
        return orders                      # jamais casser la génération d'ordres


__all__ = ["select_orders_by_board", "maybe_select_by_unified_board"]
