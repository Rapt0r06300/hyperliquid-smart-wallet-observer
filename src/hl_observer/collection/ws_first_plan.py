"""WS-first: coupe les appels REST que le firehose WebSocket couvre déjà.

Vérité mesurée: le collecteur REST-poll par wallet (open_orders, user_fills, ...)
à chaque cycle → ~4000 poids/min pour 50 leaders/15s, très au-dessus des 1200/min
de Hyperliquid → throttle. Or `allMids`, `userFills`, `l2Book`, `candle` sont DÉJÀ
poussés en temps réel par le WS. Les re-poller en REST est un gâchis pur.

Ce module prend le plan REST + l'ensemble des canaux WS confirmés VIVANTS ET FRAIS,
et désactive les items REST redondants. Conservateur: on ne coupe un REST QUE si le
WS de ce type est actif ET frais (sinon on garde le REST — jamais de trou de données).

Pur/déterministe. Lecture seule. Aucune exécution réelle.
"""

from __future__ import annotations

# Canal WS -> flag REST qu'il rend redondant.
WS_CHANNEL_TO_REST_FLAG = {
    "allMids": "all_mids",
    "userFills": "user_fills",
    "l2Book": "l2_book",
    "candle": "candles",
}

# Poids REST par item (doc HL: light=2, default=20).
_ITEM_WEIGHT = {
    "all_mids": 2, "l2_book": 20, "open_orders": 20, "frontend_open_orders": 20,
    "user_fills": 20, "user_fills_by_time": 20, "candles": 20,
}
# Items dont le coût est PAR WALLET (scalent avec le nb de leaders = moteur du throttle).
_PER_WALLET = {"open_orders", "frontend_open_orders", "user_fills", "user_fills_by_time"}


def _cycle_weight(flags: dict, *, num_wallets: int, num_coins: int) -> int:
    total = 0
    for item, w in _ITEM_WEIGHT.items():
        if not flags.get(item):
            continue
        if item in _PER_WALLET:
            total += w * max(0, int(num_wallets))
        elif item in {"l2_book", "candles"}:
            total += w * max(1, int(num_coins))
        else:
            total += w                       # global (all_mids)
    return total


def apply_ws_first(
    *, plan_flags: dict, ws_fresh_channels: set, num_wallets: int, num_coins: int = 1,
) -> dict:
    """Désactive les items REST couverts par un canal WS frais. Renvoie le plan
    réduit + le poids/cycle avant/après + les items coupés."""
    before = dict(plan_flags)
    reduced = dict(plan_flags)
    dropped: list[str] = []
    for channel, rest_flag in WS_CHANNEL_TO_REST_FLAG.items():
        if channel in (ws_fresh_channels or set()) and reduced.get(rest_flag):
            reduced[rest_flag] = False
            dropped.append(rest_flag)

    w_before = _cycle_weight(before, num_wallets=num_wallets, num_coins=num_coins)
    w_after = _cycle_weight(reduced, num_wallets=num_wallets, num_coins=num_coins)
    return {
        "flags": reduced,
        "dropped_rest_items": dropped,
        "weight_before_per_cycle": w_before,
        "weight_after_per_cycle": w_after,
        "weight_saved_per_cycle": w_before - w_after,
    }


def within_budget(
    *, weight_per_cycle: int, interval_s: float, target_weight_per_min: float = 840.0,
    num_egress_ips: int = 1,
) -> bool:
    """Le plan tient-il sous le budget/min (× IP) ?"""
    interval_s = max(1.0, float(interval_s))
    per_min = float(weight_per_cycle) * (60.0 / interval_s)
    budget = max(1.0, float(target_weight_per_min)) * max(1, int(num_egress_ips))
    return per_min <= budget


def reduce_plan_from_env(plan, env: dict | None = None):
    """Applique WS-first à un CollectionPlan si ``HYPERSMART_WS_FIRST_COLLECT`` est
    actif. Canaux frais déclarés via ``HYPERSMART_WS_FIRST_CHANNELS`` (défaut
    ``allMids,userFills``). No-op sinon. Duck-typé (marche avec tout objet ayant les
    attributs de flags + éventuellement ``model_copy``)."""
    import os

    e = env if env is not None else os.environ
    if str(e.get("HYPERSMART_WS_FIRST_COLLECT", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return plan
    raw = e.get("HYPERSMART_WS_FIRST_CHANNELS", "allMids,userFills")
    fresh = {c.strip() for c in str(raw).split(",") if c.strip()}
    if not fresh:
        return plan
    flags = {rf: bool(getattr(plan, rf, False)) for rf in WS_CHANNEL_TO_REST_FLAG.values()}
    reduced = apply_ws_first(
        plan_flags=flags, ws_fresh_channels=fresh,
        num_wallets=len(getattr(plan, "wallets", []) or []),
        num_coins=max(1, len(getattr(plan, "coins", []) or [])),
    )
    update = {k: v for k, v in reduced["flags"].items() if getattr(plan, k, None) != v}
    if not update:
        return plan
    if hasattr(plan, "model_copy"):
        return plan.model_copy(update=update)
    for k, v in update.items():
        setattr(plan, k, v)
    return plan


__all__ = ["apply_ws_first", "within_budget", "reduce_plan_from_env", "WS_CHANNEL_TO_REST_FLAG"]
