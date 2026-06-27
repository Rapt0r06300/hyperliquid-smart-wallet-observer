from __future__ import annotations

from collections import defaultdict

from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionAction, PositionLifecycle


def build_lifecycles(actions: list[PositionAction]) -> list[PositionLifecycle]:
    groups: dict[tuple[str, str], list[PositionAction]] = defaultdict(list)
    for action in actions:
        groups[(action.wallet_address.lower(), action.coin.upper())].append(action)
    lifecycles: list[PositionLifecycle] = []
    for (wallet, coin), grouped in groups.items():
        grouped.sort(key=lambda item: item.timestamp)
        confidence = sum(action.confidence for action in grouped) / len(grouped)
        warnings = [warning for action in grouped for warning in action.warnings]
        lifecycles.append(
            PositionLifecycle(
                wallet_address=wallet,
                coin=coin,
                actions=grouped,
                confidence=confidence,
                status="PARTIAL" if warnings else "RECONSTRUCTED",
                warnings=warnings,
            )
        )
    return lifecycles
