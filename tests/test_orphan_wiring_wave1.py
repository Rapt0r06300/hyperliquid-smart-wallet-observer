"""Câblage vague 1 des modules orphelins (AUDIT-B).

Prouve que les outils dormants fonctionnent: breakdown live des refus (T36)
et A/B replay des flags (T14-17/T29, exécutable en CLI module).
"""

from __future__ import annotations

from hl_observer.backtesting.ab_flag_replay import marks_by_coin, run_ab_replay
from hl_observer.ui.refusal_live import build_live_refusal_breakdown


def _refusal(reason: str, coin: str, notional: float = 25.0) -> dict:
    return {
        "status": "REJECT_NO_TRADE",
        "paper_action_type": "NO_TRADE",
        "reason": reason,
        "coin": coin,
        "leader_notional_usdc": notional,
    }


def test_live_refusal_breakdown_counts_reasons_and_coins():
    events = [
        _refusal("EDGE_TOO_SMALL", "MON"),
        _refusal("EDGE_TOO_SMALL", "MON"),
        _refusal("EDGE_TOO_SMALL", "LIT", 40.0),
        _refusal("SIGNAL_TOO_OLD", "BTC"),
        {"status": "LOCAL_REPLAY", "paper_action_type": "OPEN", "coin": "HYPE"},
    ]
    report = build_live_refusal_breakdown(events)
    assert report["total_refusals"] == 4
    assert report["distinct_reasons"] == 2
    first = report["rows"][0]
    assert first["reason"] == "EDGE_TOO_SMALL"
    assert first["count"] == 3
    assert first["share"] == 0.75
    assert "MON×2" in first["top_coins"]
    assert first["refused_notional_usdc"] == 90.0
    assert report["read_only"] is True


def test_live_refusal_breakdown_empty_is_honest():
    report = build_live_refusal_breakdown([])
    assert report["total_refusals"] == 0
    assert report["rows"] == []


def _candidate(coin: str, side: str, entry: float, ts: float) -> dict:
    return {
        "coin": coin,
        "direction": side,
        "current_mid": entry,
        "recorded_at": ts,
        "edge_remaining_bps": 40.0,
        "notional_usd": 40.0,
    }


def test_ab_flag_replay_runs_deterministically_on_synthetic_path():
    base = 1_000.0
    candidates = [_candidate("HYPE", "LONG", 100.0, base)]
    marks = [
        {"coin": "HYPE", "ts": base + i * 60.0, "mid": price}
        for i, price in enumerate([100.0, 100.4, 100.9, 101.3, 100.8, 101.6])
    ]
    report = run_ab_replay(candidates, marks, horizon_min=6.0)
    assert set(report) >= {"arm_a", "arm_b", "delta_net_usd", "honesty"}
    assert report["arm_a"]["candidates_seen"] == 1
    again = run_ab_replay(candidates, marks, horizon_min=6.0)
    assert again["delta_net_usd"] == report["delta_net_usd"]  # déterminisme


def test_marks_by_coin_orders_by_time():
    rows = [
        {"coin": "BTC", "ts": 2_000, "mid": 50_100.0},
        {"coin": "BTC", "ts": 1_000, "mid": 50_000.0},
    ]
    series = marks_by_coin(rows)
    assert [p for _, p in series["BTC"]] == [50_000.0, 50_100.0]
