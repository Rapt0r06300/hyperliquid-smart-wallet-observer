from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HotWatchSlot:
    slot_id: int
    wallet_address: str
    priority: float
    assigned_at_ms: int
    expires_at_ms: int
    reason: str
    source: str
    last_event_at_ms: int | None = None


def rotate_hot_watch(
    candidates: list[tuple[str, float, int | None]],
    *,
    now_ms: int,
    max_slots: int = 10,
    slot_ttl_ms: int = 60_000,
    existing_slots: list[HotWatchSlot] | None = None,
) -> list[HotWatchSlot]:
    """Keep active wallets, replace expired low-priority slots, never exceed 10."""

    max_slots = max(0, min(10, int(max_slots)))
    existing = existing_slots or []
    active_existing = [
        slot
        for slot in existing
        if slot.expires_at_ms > now_ms and (slot.last_event_at_ms is not None and now_ms - slot.last_event_at_ms <= slot_ttl_ms)
    ]
    by_wallet = {slot.wallet_address.lower(): slot for slot in active_existing}
    ordered_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    for wallet, priority, last_event_at_ms in ordered_candidates:
        key = wallet.lower()
        if key in by_wallet:
            continue
        if len(by_wallet) >= max_slots:
            break
        by_wallet[key] = HotWatchSlot(
            slot_id=len(by_wallet) + 1,
            wallet_address=key,
            priority=float(priority),
            assigned_at_ms=now_ms,
            expires_at_ms=now_ms + max(1, slot_ttl_ms),
            reason="priority_rotation",
            source="hot_watch_rotation",
            last_event_at_ms=last_event_at_ms,
        )
    slots = sorted(by_wallet.values(), key=lambda slot: slot.priority, reverse=True)[:max_slots]
    for index, slot in enumerate(slots, start=1):
        slot.slot_id = index
    return slots

