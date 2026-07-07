"""A4 — Runtime scale/perf: plan de scan wallets + budget API + latence + deltas UI.

Compose tiered_scanner + api_budget (scanner à étages sous contrainte 10 WS/IP + zéro
429), latency_tracker (métriques par étage), status_delta (UI incrémentale). Pur, testé.
Le partage d'état (budget, tracker) se fait via singletons process-local. Câblage =
appeler plan_scan_cycle() dans la boucle du scanner et push_latency() dans le tick.
"""

from __future__ import annotations

from hl_observer.perf.latency_tracker import get_latency_tracker
from hl_observer.ui.status_delta import compute_status_delta
from hl_observer.wallets.api_budget import ApiBudget, hl_request_weight
from hl_observer.wallets.tiered_scanner import assign_tiers, due_for_refresh, ws_subscription_count

_BUDGET: ApiBudget | None = None


def get_api_budget() -> ApiBudget:
    global _BUDGET
    if _BUDGET is None:
        _BUDGET = ApiBudget(capacity=1200.0, refill_per_sec=100.0)
    return _BUDGET


def plan_scan_cycle(
    *, scored_wallets: dict[str, float], last_seen_ms: dict[str, int], now_ms: int,
    items_per_wallet: int = 20, max_ws: int = 10,
) -> dict:
    """Un cycle de scan: tiers, WS (≤max_ws), et wallets REST autorisés par le budget."""
    plans = assign_tiers(scored_wallets, max_ws=max_ws)
    budget = get_api_budget()
    due = due_for_refresh(plans, last_seen_ms, now_ms)
    granted, deferred = [], []
    for wallet in due:
        w = hl_request_weight(items_returned=items_per_wallet)
        if budget.try_consume(w, now_ms):
            granted.append(wallet)
        else:
            deferred.append(wallet)
    return {
        "ws_subscribed": ws_subscription_count(plans),
        "rest_due": len(due),
        "rest_granted": granted,
        "rest_deferred": deferred,   # temporisés (backoff) → jamais de 429
        "budget": budget.stats(),
    }


def push_latency(*, leader_ms: float, detect_ms: float, decision_ms: float, fill_ms: float) -> None:
    get_latency_tracker().record_decision(leader_ms=leader_ms, detect_ms=detect_ms, decision_ms=decision_ms, fill_ms=fill_ms)


def latency_snapshot() -> dict:
    return get_latency_tracker().report()


def ui_delta(prev: dict | None, curr: dict) -> dict:
    return compute_status_delta(prev, curr)


__all__ = ["get_api_budget", "plan_scan_cycle", "push_latency", "latency_snapshot", "ui_delta"]
