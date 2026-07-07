"""SCALE — Scanner de wallets à étages (contrainte HL: 10 users WS/IP max).

On ne peut pas suivre des centaines de wallets en WebSocket. Architecture:
  - HOT  : top-N (défaut 10) suivis en WS temps réel;
  - WARM : rotation REST fréquente (candidats prometteurs);
  - COLD : rotation REST lente (surveillance large);
  - DISCOVERY: pool découverte, promu s'il score.
Promotion/rétrogradation par SCORE (PF net, fraîcheur, activité). Pur et
déterministe: décide QUI suivre et à QUELLE cadence, sans I/O réseau ici.
"""

from __future__ import annotations

from dataclasses import dataclass

HOT, WARM, COLD, DISCOVERY = "HOT", "WARM", "COLD", "DISCOVERY"
_REFRESH_MS = {HOT: 0, WARM: 15_000, COLD: 120_000, DISCOVERY: 900_000}  # HOT=WS continu


@dataclass(frozen=True, slots=True)
class WalletTierPlan:
    wallet: str
    tier: str
    score: float
    refresh_ms: int
    ws_subscribed: bool


def assign_tiers(
    scored_wallets: dict[str, float],
    *,
    max_ws: int = 10,
    warm_size: int = 40,
    cold_size: int = 250,
) -> tuple[WalletTierPlan, ...]:
    """Range les wallets par score décroissant en étages, WS réservé au top max_ws."""

    ranked = sorted(scored_wallets.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    plans: list[WalletTierPlan] = []
    for i, (wallet, score) in enumerate(ranked):
        if i < max_ws:
            tier = HOT
        elif i < max_ws + warm_size:
            tier = WARM
        elif i < max_ws + warm_size + cold_size:
            tier = COLD
        else:
            tier = DISCOVERY
        plans.append(WalletTierPlan(
            wallet=str(wallet), tier=tier, score=float(score),
            refresh_ms=_REFRESH_MS[tier], ws_subscribed=(tier == HOT),
        ))
    return tuple(plans)


def ws_subscription_count(plans: tuple[WalletTierPlan, ...]) -> int:
    return sum(1 for p in plans if p.ws_subscribed)


def due_for_refresh(plans: tuple[WalletTierPlan, ...], last_seen_ms: dict[str, int], now_ms: int) -> tuple[str, ...]:
    """Wallets REST dont la cadence est échue (HOT exclu: il est en WS continu)."""

    due: list[str] = []
    for p in plans:
        if p.tier == HOT or p.refresh_ms <= 0:
            continue
        last = int(last_seen_ms.get(p.wallet, 0))
        if now_ms - last >= p.refresh_ms:
            due.append(p.wallet)
    return tuple(due)


def apply_promotions(
    current: dict[str, str],
    scored_wallets: dict[str, float],
    *,
    max_ws: int = 10,
    warm_size: int = 40,
    cold_size: int = 250,
) -> dict[str, dict]:
    """Compare l'ancienne assignation à la nouvelle → mouvements de tier."""

    new_plans = {p.wallet: p.tier for p in assign_tiers(scored_wallets, max_ws=max_ws, warm_size=warm_size, cold_size=cold_size)}
    order = {DISCOVERY: 0, COLD: 1, WARM: 2, HOT: 3}
    moves: dict[str, dict] = {}
    for wallet, new_tier in new_plans.items():
        old = current.get(wallet)
        if old is None or old == new_tier:
            continue
        moves[wallet] = {
            "from": old, "to": new_tier,
            "direction": "PROMOTED" if order[new_tier] > order.get(old, 0) else "DEMOTED",
        }
    return moves


__all__ = [
    "HOT", "WARM", "COLD", "DISCOVERY", "WalletTierPlan",
    "assign_tiers", "ws_subscription_count", "due_for_refresh", "apply_promotions",
]
