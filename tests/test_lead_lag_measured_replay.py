from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.simulation.lead_lag_measured_replay import (
    load_runtime_latency_evidence,
    replay_measured_lead_lag,
)


def test_runtime_latency_evidence_requires_real_sample_count(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "data" / "lead_lag_event_decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "latency_ms": value,
            "latency_kind": "LOCAL_MONOTONIC_DISPATCH",
            "sample_only": True,
            "real_execution": False,
        }
        for value in range(1, 21)
    ]
    rows.append(
        {
            "latency_ms": 0,
            "latency_kind": "LEGACY_WALL_DISPATCH",
            "sample_only": True,
            "real_execution": False,
        }
    )
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


def test_last_causal_book_remains_executable_until_a_new_update() -> None:
    tape, l2 = _fixture()
    base_ms = 1_786_552_000_000
    l2["ETH"] = [
        row
        for row in l2["ETH"]
        if (int(row["ts_ms"]) - base_ms) % 1_000 != 20
    ]

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

    assert replay["coverage"]["observable"] >= 5
    entries = [
        row
        for rows in replay["ledgers"].values()
        for row in rows
        if row.get("evt") == "ENTREE"
    ]
    assert entries
    assert all(int(row["ts"]) % 1_000 == 20 for row in entries)


def test_stale_book_waits_for_next_observation_and_moves_execution_time() -> None:
    tape, l2 = _fixture()
    replay = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=50,
        latency_evidence=_latency(),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=1,
        max_book_age_ms=10.0,
        max_execution_observation_delay_ms=100.0,
        min_episodes=1,
    )

    assert replay["coverage"]["observable"] >= 5
    exits = [
        row
        for rows in replay["ledgers"].values()
        for row in rows
        if row.get("evt") == "SORTIE"
    ]
    assert exits
    # target is trigger+70 ms, so the observed +120 ms book delays execution.
    assert all(int(row["ts"]) % 1_000 == 120 for row in exits)


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


def test_raw_diagnostics_explain_no_trade_without_certifying_pnl() -> None:
    tape, l2 = _fixture()
    replay = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        latency_evidence=_latency(),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=999,
        min_episodes=1,
    )

    assert sum(segment["fills"] for segment in replay["segments"].values()) == 0
    assert replay["decision_counts"] == {
        "INSUFFICIENT_PRIOR_HISTORY": replay["signals"]
    }
    diagnostics = replay["raw_observation_diagnostics"]
    assert diagnostics["diagnostic_only"] is True
    assert diagnostics["selection_eligible"] is False
    assert diagnostics["not_admitted_pnl"] is True
    assert diagnostics["counted_as_certified_pnl"] is False
    assert diagnostics["observations"] == replay["signals"]
    assert diagnostics["full_fill_observations"] == replay["signals"]
    assert diagnostics["net_pnl_usd_if_all_executable_taken"] > 0.0
    assert diagnostics["reconciliation_error_usd"] == 0.0


def test_raw_diagnostics_do_not_change_with_the_admission_history_gate() -> None:
    tape, l2 = _fixture()
    common = {
        "shock_threshold_bps": 8.0,
        "horizon_ms": 100,
        "latency_evidence": _latency(),
        "notional_usd": 100.0,
        "fee_bps": 1.0,
        "min_episodes": 1,
    }

    admitted = replay_measured_lead_lag(tape, l2, min_history=1, **common)
    refused = replay_measured_lead_lag(tape, l2, min_history=999, **common)

    assert admitted["raw_observation_diagnostics"] == refused[
        "raw_observation_diagnostics"
    ]
    assert sum(segment["fills"] for segment in admitted["segments"].values()) > 0
    assert sum(segment["fills"] for segment in refused["segments"].values()) == 0


def test_direction_flip_is_repriced_and_remains_diagnostic_only() -> None:
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

    continuation = replay["raw_observation_diagnostics"]
    flipped = replay["raw_direction_flip_diagnostics"]
    assert continuation["net_pnl_usd_if_all_executable_taken"] > 0.0
    assert flipped["net_pnl_usd_if_all_executable_taken"] < 0.0
    assert flipped["diagnostic_only"] is True
    assert flipped["selection_eligible"] is False
    assert flipped["may_change_strategy"] is False
    assert flipped["counterfactual_type"] == (
        "DIRECTION_FLIP_SAME_CAUSAL_EXECUTION_BOOKS"
    )
    # The placebo is the actually repriced opposite side, not the original
    # spread reused with a negated markout.
    assert replay["placebo"]["sample_count"] > 0
    assert replay["placebo_net"] < 0.0


def test_extreme_reversal_uses_opposite_executable_sides_without_lookahead() -> None:
    tape, l2 = _fixture()
    continuation = replay_measured_lead_lag(
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
    reversal = replay_measured_lead_lag(
        tape,
        l2,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        latency_evidence=_latency(),
        notional_usd=100.0,
        fee_bps=1.0,
        min_history=1,
        min_episodes=1,
        direction_multiplier=-1,
    )

    assert continuation["direction_policy"] == "SHOCK_CONTINUATION"
    assert reversal["direction_policy"] == "EXTREME_SHOCK_REVERSAL"
    assert reversal["placebo_direction_policy"] == "SHOCK_CONTINUATION"
    assert reversal["raw_observation_diagnostics"]["direction_multiplier"] == -1
    assert reversal["raw_direction_flip_diagnostics"]["direction_multiplier"] == 1
    assert (
        reversal["raw_observation_diagnostics"][
            "net_pnl_usd_if_all_executable_taken"
        ]
        == continuation["raw_direction_flip_diagnostics"][
            "net_pnl_usd_if_all_executable_taken"
        ]
    )
    assert (
        reversal["raw_direction_flip_diagnostics"][
            "net_pnl_usd_if_all_executable_taken"
        ]
        == continuation["raw_observation_diagnostics"][
            "net_pnl_usd_if_all_executable_taken"
        ]
    )


def test_direction_multiplier_refuses_ambiguous_policy() -> None:
    tape, l2 = _fixture()
    with pytest.raises(ValueError, match="direction_multiplier"):
        replay_measured_lead_lag(
            tape,
            l2,
            shock_threshold_bps=8.0,
            horizon_ms=100,
            latency_evidence=_latency(),
            direction_multiplier=0,
        )
