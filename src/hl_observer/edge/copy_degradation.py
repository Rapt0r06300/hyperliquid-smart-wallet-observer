from __future__ import annotations


def entry_copy_degradation_bps(
    *,
    side: str,
    leader_entry_price: float,
    copy_entry_price: float,
) -> float:
    if leader_entry_price <= 0:
        raise ValueError("leader_entry_price must be positive")
    direction = 1.0 if side.lower() == "long" else -1.0
    return direction * (copy_entry_price - leader_entry_price) / leader_entry_price * 10000.0
