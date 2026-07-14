from __future__ import annotations

from pathlib import Path

from hl_observer.config.settings import Settings
from hl_observer.decision_engine.local_engine import DecisionAction, LocalDecisionEngine
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.loops.candidate_factory import (
    build_signal_candidates_from_observation,
    build_signal_candidates_from_position_deltas,
)
from hl_observer.loops.dashboard_payload import build_loop_dashboard_payload
from hl_observer.loops.engine import LoopEngineeringRunner
from hl_observer.loops.memory import LoopMemoryStore
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.testnet.models import TestnetAction, unix_ms


def _book() -> dict[str, object]:
    return {
        "levels": [
            [{"px": "59999", "sz": "0.5"}],
            [{"px": "60001", "sz": "0.5"}],
        ]
    }


def test_candidate_factory_builds_open_long_from_readonly_user_fill() -> None:
    now = unix_ms()
    observation = MainnetObservation(
        source="hyperliquid_mainnet_readonly_test",
        all_mids={"BTC": 60_000.0},
        l2_books={"BTC": _book()},
        wallet_fills={
            "0x1111111111111111111111111111111111111111": [
                {
                    "coin": "BTC",
                    "dir": "Open Long",
                    "px": "60000",
                    "sz": "0.01",
                    "time": now,
                    "hash": "0xabc",
                }
            ]
        },
        observed_at_ms=now,
    )

    report = build_signal_candidates_from_observation(observation)

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.coin == "BTC"
    assert candidate.side == "long"
    assert candidate.signal_type == "open"
    assert candidate.source_wallet == "0x1111111111111111111111111111111111111111"
    assert candidate.edge_remaining_bps > 25
    assert not report.skipped


def test_candidate_factory_skips_unknown_fill_direction() -> None:
    observation = MainnetObservation(
        source="hyperliquid_mainnet_readonly_test",
        all_mids={"BTC": 60_000.0},
        wallet_fills={
            "0x1111111111111111111111111111111111111111": [
                {"coin": "BTC", "dir": "Mystery", "px": "60000"}
            ]
        },
    )

    report = build_signal_candidates_from_observation(observation)

    assert report.candidates == []
    assert report.skipped[0].reason == "unsupported_fill_direction"


def test_candidate_factory_builds_open_short_from_position_delta() -> None:
    now = unix_ms()
    report = build_signal_candidates_from_position_deltas(
        [
            {
                "wallet_address": "0x3333333333333333333333333333333333333333",
                "coin": "ETH",
                "action": "OPEN_SHORT",
                "price": 3000.0,
                "detected_at_ms": now,
                "new_size": -0.25,
            }
        ],
        all_mids={"ETH": 3000.0},
        l2_books={"ETH": _book()},
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.id.startswith("pd-")
    assert candidate.coin == "ETH"
    assert candidate.side == "short"
    assert candidate.signal_type == "open"
    assert candidate.source_wallet == "0x3333333333333333333333333333333333333333"
    assert candidate.edge_remaining_bps > 20


def test_candidate_factory_skips_unknown_position_delta() -> None:
    report = build_signal_candidates_from_position_deltas(
        [
            {
                "wallet_address": "0x4444444444444444444444444444444444444444",
                "coin": "ETH",
                "action": "UNKNOWN",
                "price": 3000.0,
            }
        ],
        all_mids={"ETH": 3000.0},
    )

    assert report.candidates == []
    assert report.skipped[0].reason == "unknown_delta"


def test_decision_engine_maps_close_signal_to_close_request() -> None:
    candidate = SignalCandidate(
        id="sig-close-btc",
        source_wallet="0x2222222222222222222222222222222222222222",
        coin="BTC",
        side="long",
        signal_type="close",
        observed_price=60_000.0,
        timestamp_ms=unix_ms(),
        signal_age_ms=100,
        wallet_score=95.0,
        signal_score=90.0,
        edge_remaining_bps=80.0,
        estimated_fee_bps=4.0,
        estimated_spread_bps=1.0,
        estimated_slippage_bps=1.0,
        orderbook_depth_usdc=1_000_000.0,
    )

    decision = LocalDecisionEngine(Settings()).decide_from_candidate(
        candidate,
        notional_usdc=2.0,
        cloid="close-btc-test",
    )

    assert decision.action is DecisionAction.EXIT
    assert decision.order_request is not None
    assert decision.order_request.action is TestnetAction.CLOSE
    assert decision.order_request.reduce_only is True
    assert decision.order_request.notional_usdc == 0.0


def test_loop_dashboard_payload_reads_latest_result(tmp_path: Path) -> None:
    memory = LoopMemoryStore(tmp_path / "learning")
    runner = LoopEngineeringRunner(settings=Settings(), memory=memory)
    observation = MainnetObservation(
        source="hyperliquid_mainnet_readonly_test",
        all_mids={"BTC": 60_000.0},
        observed_at_ms=unix_ms(),
    )
    runner.run_with_observation(observation=observation, candidates=[])

    payload = build_loop_dashboard_payload(tmp_path / "learning")

    assert payload["status"] == "READY"
    assert payload["has_latest_result"] is True
    assert payload["has_latest_trace"] is True
    assert payload["latest_result"]["learning"]["total_decisions"] == 0
    assert payload["latest_decision_trace"] == []


def test_loop_dashboard_payload_reads_decision_trace(tmp_path: Path, monkeypatch) -> None:
    # Ce test verifie que la TRACE remonte au dashboard -- pas que le trade soit bon.
    # Le noyau (G2) refuse desormais toute entree de famille DISCRETIONNAIRE_PUBLIC (zone morte
    # mesuree). On l'eteint EXPLICITEMENT ici pour tester la plomberie de la trace ; le verdict
    # du noyau, lui, est epingle par tests/test_noyau_unique.py et test_testnet_pipeline_slice.py.
    monkeypatch.setenv("HYPERSMART_NOYAU_AUTORITAIRE", "0")
    now = unix_ms()
    memory = LoopMemoryStore(tmp_path / "learning")
    runner = LoopEngineeringRunner(settings=Settings(), memory=memory)
    observation = MainnetObservation(
        source="hyperliquid_mainnet_readonly_test",
        all_mids={"BTC": 60_000.0},
        observed_at_ms=now,
    )
    candidate = SignalCandidate(
        id="sig-open-btc",
        source_wallet="0x5555555555555555555555555555555555555555",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=60_000.0,
        timestamp_ms=now,
        signal_age_ms=100,
        wallet_score=95.0,
        signal_score=90.0,
        edge_remaining_bps=80.0,
        estimated_fee_bps=4.0,
        estimated_spread_bps=1.0,
        estimated_slippage_bps=1.0,
        orderbook_depth_usdc=1_000_000.0,
    )
    runner.run_with_observation(observation=observation, candidates=[candidate])

    payload = build_loop_dashboard_payload(tmp_path / "learning")

    trace = payload["latest_decision_trace"]
    assert len(trace) == 1
    assert trace[0]["candidate_id"] == "sig-open-btc"
    assert trace[0]["coin"] == "BTC"
    assert trace[0]["decision_action"] == "ENTER"
    assert trace[0]["order_action"] == "open"
