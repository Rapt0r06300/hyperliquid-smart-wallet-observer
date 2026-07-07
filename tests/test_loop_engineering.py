from __future__ import annotations

from pathlib import Path

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.loops.engine import LoopEngineeringRunner, load_signal_candidates
from hl_observer.loops.memory import LoopMemoryStore
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.testnet.adapters import FakeTestnetExchangeAdapter


def _candidate() -> SignalCandidate:
    return SignalCandidate(
        id="loop-sig-1",
        source_wallet="0x2222222222222222222222222222222222222222",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=60_000.0,
        timestamp_ms=1,
        signal_age_ms=100,
        wallet_score=95.0,
        signal_score=92.0,
        edge_remaining_bps=85.0,
        estimated_fee_bps=4.0,
        estimated_spread_bps=1.0,
        estimated_slippage_bps=1.0,
        orderbook_depth_usdc=1_000_000.0,
    )


def _observation() -> MainnetObservation:
    return MainnetObservation(
        source="hyperliquid_mainnet_readonly_test",
        all_mids={"BTC": 60_000.0},
        l2_books={"BTC": {"levels": []}},
        wallet_states={"0x2222222222222222222222222222222222222222": {"assetPositions": []}},
        wallet_fills={"0x2222222222222222222222222222222222222222": [{"coin": "BTC"}]},
    )


def test_loop_engineering_prepares_decision_without_execution(tmp_path: Path) -> None:
    memory = LoopMemoryStore(tmp_path / "learning")
    runner = LoopEngineeringRunner(settings=Settings(), memory=memory)

    result = runner.run_with_observation(
        observation=_observation(),
        candidates=[_candidate()],
        execute_testnet=False,
        confirmed=False,
    )

    assert result.thesis.status == "READY"
    assert result.learning.total_decisions == 1
    assert result.learning.prepared_requests == 1
    assert result.learning.accepted_testnet == 0
    assert result.feedback[0].execution_status == "PREPARED_ONLY"
    assert memory.events_path.exists()
    assert memory.latest_markdown_path.exists()
    logs_to_send = tmp_path / "logs" / "logs à envoyer"
    assert (logs_to_send / "latest_loop_result.json").exists()
    assert (logs_to_send / "latest_decision_trace.json").exists()
    assert (logs_to_send / "latest_loop_report.md").exists()
    assert "loop-sig-1" in (logs_to_send / "latest_decision_trace.json").read_text(encoding="utf-8")


def test_loop_engineering_fake_testnet_executes_only_when_explicitly_confirmed(tmp_path: Path) -> None:
    adapter = FakeTestnetExchangeAdapter(prices={"BTC": 60_000.0})
    runner = LoopEngineeringRunner.with_fake_testnet_executor(
        Settings(),
        adapter=adapter,
        project_root=tmp_path,
        confirmed=True,
    )

    result = runner.run_with_observation(
        observation=_observation(),
        candidates=[_candidate()],
        execute_testnet=True,
        confirmed=True,
        notional_usdc=1.0,
    )

    assert result.learning.accepted_testnet == 1
    assert result.feedback[0].execution_status == "ACCEPTED"
    assert adapter.get_testnet_positions()[0].coin == "BTC"
    assert (tmp_path / "logs").exists()
    journals = list((tmp_path / "logs").rglob("testnet_decisions_latest.jsonl"))
    assert journals
    assert "accepted" in journals[0].read_text(encoding="utf-8")


def test_load_signal_candidates_accepts_windows_utf8_bom(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text("[" + _candidate().model_dump_json() + "]", encoding="utf-8-sig")

    candidates = load_signal_candidates(candidate_path)

    assert len(candidates) == 1
    assert candidates[0].id == "loop-sig-1"
