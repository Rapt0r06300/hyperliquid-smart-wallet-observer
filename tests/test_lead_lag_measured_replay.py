from __future__ import annotations

import json
from pathlib import Path

from hl_observer.simulation.lead_lag_measured_replay import (
    load_runtime_latency_evidence,
    replay_measured_lead_lag,
)


def test_runtime_latency_evidence_requires_real_sample_count(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "data" / "lead_lag_event_decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"latency_ms": value, "real_execution": False} for value in range(1, 21)]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    evidence = load_runtime_latency_evidence(tmp_path, min_samples=20)
    assert evidence["measured"] is True
    assert evidence["samples"] == 20
    assert evidence["p95_ms"] == 19.0

    stricter = load_runtime_latency_evidence(tmp_path, min_samples=21)
    assert stricter["measured"] is False


def _fixture(*, capacity_usd: float = 1_000.0):
    base_ms = 1_786_552_000_000
    trades = [(base_ms * 1_000_000, 100.0, 1.0)]
    l2 = []
    size = capacity_usd / 100.0
    for index in range(1, 7):
        trigger = base_ms + index * 1_000
        trades.append((trigger * 1_000_000, 100.0 + index * 0.2, 1.0))
        # Causal book immediately before trigger.
        l2.append({
            "coin": "ETH", "ts_ms": trigger - 1, "bid": 99.99, "ask": 100.01,
            "bid_top_usd": 99.99 * size, "ask_top_usd": 100.01 * size,
        })
        # Executable book only after measured 20 ms runtime latency.
        entry_mid = 100.0 + index * 0.02
        l2.append({
            "coin": "ETH", "ts_ms": trigger + 20,
            "bid": entry_mid - 0.01, "ask": entry_mid + 0.01,
            "bid_top_usd": (entry_mid - 0.01) * size,
            "ask_top_usd": (entry_mid + 0.01) * size,
        })
        exit_mid = entry_mid + 0.20
        l2.append({
            "coin": "ETH", "ts_ms": trigger + 120,
            "bid": exit_mid - 0.01, "ask": exit_mid + 0.01,
            "bid_top_usd": (exit_mid - 0.01) * size,
            "ask_top_usd": (exit_mid + 0.01) * size,
        })
    return {"ETH": {"TRADE": trades, "HL": [], "BIN": []}}, {"ETH": sorted(l2, key=lambda row: row["ts_ms"])}


def _latency(measured: bool = True) -> dict:
    return {"measured": measured, "p95_ms": 20.0 if measured else None, "samples": 30 if measured else 0}


def test_measured_replay_uses_delayed_executable_l2_and_full_capacity() -> None:
    tape, l2 = _fixture()
    replay = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        latency_evidence=_latency(),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=1,
        min_episodes=1,
    )

    assert replay["costs_measured"] is True
    assert replay["coverage"]["observable"] >= 5
    assert replay["coverage"]["capacity_missed"] == 0
    all_fills = sum(segment["fills"] for segment in replay["segments"].values())
    assert all_fills > 0
    assert replay["fee_source"] == "FROZEN_CONSERVATIVE_TAKER_ROUND_TRIP"
    assert replay["latency_rule"] == "P95_EMBEDDED_IN_DELAYED_ENTRY_PRICE_NO_DOUBLE_CHARGE"


def test_missing_latency_proof_can_never_be_liquidatable() -> None:
    tape, l2 = _fixture()
    replay = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        latency_evidence=_latency(False),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=1,
        min_episodes=1,
    )
    assert replay["costs_measured"] is False
    assert not any(segment["LIQUIDATABLE_NET"] for segment in replay["segments"].values())


def test_top_book_capacity_below_full_notional_is_missed_not_half_filled() -> None:
    tape, l2 = _fixture(capacity_usd=40.0)
    replay = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        latency_evidence=_latency(),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=1,
        min_episodes=1,
    )
    assert replay["coverage"]["capacity_missed"] > 0
    assert sum(segment["fills"] for segment in replay["segments"].values()) == 0
