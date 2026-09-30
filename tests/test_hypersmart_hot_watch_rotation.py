from __future__ import annotations

from hyper_smart_observer.realtime_monitor.hot_watch_rotation import HotWatchSlot, rotate_hot_watch


def test_hot_watch_never_exceeds_ten_slots_and_orders_by_priority() -> None:
    candidates = [("0x" + f"{i:040x}", float(i), 1_800_000_000_000) for i in range(1, 25)]

    slots = rotate_hot_watch(candidates, now_ms=1_800_000_000_000, max_slots=50)

    assert len(slots) == 10
    assert slots[0].priority > slots[-1].priority
    assert [slot.slot_id for slot in slots] == list(range(1, 11))


def test_hot_watch_keeps_recent_active_existing_slot() -> None:
    existing = HotWatchSlot(
        slot_id=1,
        wallet_address="0x" + "a" * 40,
        priority=999.0,
        assigned_at_ms=1,
        expires_at_ms=2_000,
        reason="active",
        source="test",
        last_event_at_ms=1_500,
    )

    slots = rotate_hot_watch(
        [("0x" + "b" * 40, 1.0, 1_600)],
        now_ms=1_700,
        max_slots=2,
        slot_ttl_ms=1_000,
        existing_slots=[existing],
    )

    assert slots[0].wallet_address == "0x" + "a" * 40
    assert len(slots) == 2
