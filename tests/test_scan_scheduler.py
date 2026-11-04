from __future__ import annotations

from hl_observer.wallets.scan_scheduler import plan_wallet_scans


def _wallet(index: int) -> str:
    return "0x" + f"{index:040x}"


def test_plan_wallet_scans_is_bounded_deterministic_and_exposes_starvation():
    now = 1_000_000
    candidates = [
        {"wallet_address": _wallet(index), "priority_score": float(index), "last_state_ms": now}
        for index in range(1000)
    ]
    candidates.extend([
        {"wallet_address": _wallet(1001), "priority_score": 99_999.0, "last_state_ms": now - 60_001},
        {"wallet_address": _wallet(1002), "priority_score": 99_998.0},
        {"wallet_address": "0x123...456", "priority_score": 99_997.0, "last_state_ms": now},
    ])

    plan = plan_wallet_scans(candidates, now_ms=now, max_wallets=1000, batch_size=100)

    assert len(plan.selected_wallets) == 1000
    assert plan.selected_wallets[0] == _wallet(999)
    assert plan.batch_count == 10
    assert plan.starvation is False
    assert {item["reason"] for item in plan.no_trade} == {"STALE_STATE", "STATE_UNKNOWN"}
    assert plan.skipped_invalid == 1


def test_plan_wallet_scans_marks_capacity_backlog_without_scanning_stale_state():
    now = 2_000_000
    candidates = [
        {"wallet_address": _wallet(index), "priority_score": 1.0, "last_state_ms": now}
        for index in range(3)
    ]

    plan = plan_wallet_scans(candidates, now_ms=now, max_wallets=2, batch_size=1)

    assert plan.starvation is True
    assert plan.selected_wallets == (_wallet(0), _wallet(1))
    assert plan.as_dict()["real_execution"] is False
