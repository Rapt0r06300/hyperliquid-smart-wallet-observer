"""Plan read-only wallet subscriptions under Hyperliquid limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    selected_wallets: tuple[str, ...]
    rejected_wallets: tuple[dict[str, object], ...] = field(default_factory=tuple)
    max_unique_users: int = 10

    @property
    def safe_for_ws(self) -> bool:
        return len(self.selected_wallets) <= self.max_unique_users


def plan_wallet_subscriptions(
    wallets: Iterable[str],
    *,
    scores: dict[str, float] | None = None,
    max_unique_users: int = 10,
) -> SubscriptionPlan:
    """Select the highest-score unique wallets for read-only WS monitoring."""

    score_map = {str(k).lower(): float(v) for k, v in (scores or {}).items()}
    unique: dict[str, float] = {}
    rejected: list[dict[str, object]] = []
    for raw in wallets:
        wallet = str(raw or "").strip().lower()
        if not wallet:
            continue
        if wallet in unique:
            rejected.append({"wallet": wallet, "reason": "DUPLICATE_WALLET"})
            continue
        unique[wallet] = score_map.get(wallet, 0.0)
    ranked = sorted(unique.items(), key=lambda item: (-item[1], item[0]))
    selected = tuple(wallet for wallet, _ in ranked[: max(0, int(max_unique_users))])
    for wallet, score in ranked[len(selected) :]:
        rejected.append({"wallet": wallet, "score": score, "reason": "WS_UNIQUE_USER_LIMIT"})
    return SubscriptionPlan(selected_wallets=selected, rejected_wallets=tuple(rejected), max_unique_users=max_unique_users)


__all__ = ["SubscriptionPlan", "plan_wallet_subscriptions"]
