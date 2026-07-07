from __future__ import annotations

from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.pipeline.v12_decision_pipeline import (
    V12DecisionPipelineConfig,
    V12DecisionPipelineInput,
    run_v12_decision_pipeline,
)
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.storage.raw_store import RawStore
from hl_observer.storage.run_context import RunContext
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore


WALLET = "0x" + "c" * 40


def _cfg() -> V12DecisionPipelineConfig:
    return V12DecisionPipelineConfig(
        min_edge_bps=30.0,
        spread_bps=1.0,
        slippage_bps=1.0,
        fee_bps=2.0,
        funding_estimate_bps=0.0,
        top_depth_usdt=200_000.0,
        wallet_score=95.0,
        signal_score=92.0,
        paper_config=PaperEngineConfig(max_position_usdt=50.0, default_top_depth_usdt=200_000.0),
    )


def test_v12_decision_pipeline_opens_then_follows_leader_close(tmp_path):
    store = V12SQLiteStore(tmp_path / "v12.sqlite3")
    raw_store = RawStore()
    engine = PaperEngine(config=_cfg().paper_config)

    open_result = run_v12_decision_pipeline(
        V12DecisionPipelineInput(
            wallet=WALLET,
            observed_at_ms=1_700_000_000_200,
            market_mids={"HYPE": 100.5},
            leader_expected_edge_bps_by_coin={"HYPE": 80.0},
            run_context=RunContext.TEST_FIXTURE,
            raw_fills=(
                {
                    "coin": "HYPE",
                    "dir": "Open Long",
                    "side": "B",
                    "sz": "0.5",
                    "px": "100",
                    "time": 1_700_000_000_000,
                    "startPosition": "0",
                    "tid": "open-1",
                },
            ),
        ),
        config=_cfg(),
        paper_engine=engine,
        store=store,
        raw_store=raw_store,
    )

    assert len(open_result.fills) == 1
    assert open_result.lifecycle_events[0].action == LifecycleAction.OPEN_LONG
    assert open_result.leader_deltas[0].safe_for_paper_candidate
    assert open_result.edge_estimates[open_result.leader_deltas[0].delta_id].accepted
    assert open_result.paper_results[0].accepted
    assert open_result.paper_results[0].trade is not None
    assert open_result.paper_results[0].trade.action == "OPEN"
    assert len(engine.positions) == 1
    assert open_result.raw_events_stored == 1
    assert open_result.persisted_counts["v12_edge_estimates"] == 1
    assert open_result.persisted_counts["v12_decision_evidence"] == 1

    close_result = run_v12_decision_pipeline(
        V12DecisionPipelineInput(
            wallet=WALLET,
            observed_at_ms=1_700_000_010_200,
            market_mids={"HYPE": 103.0},
            # Closing follows the leader's local paper position; no new entry
            # edge is required, but the real current mid still is.
            leader_expected_edge_bps_by_coin={},
            run_context=RunContext.TEST_FIXTURE,
            raw_fills=(
                {
                    "coin": "HYPE",
                    "dir": "Close Long",
                    "side": "A",
                    "sz": "0.5",
                    "px": "102",
                    "time": 1_700_000_010_000,
                    "startPosition": "0.5",
                    "closedPnl": "1.0",
                    "tid": "close-1",
                },
            ),
        ),
        config=_cfg(),
        paper_engine=engine,
        store=store,
        raw_store=raw_store,
    )

    assert close_result.lifecycle_events[0].action == LifecycleAction.CLOSE_LONG
    assert close_result.paper_results[0].accepted
    assert close_result.paper_results[0].trade is not None
    assert close_result.paper_results[0].trade.action == "CLOSE"
    assert close_result.paper_results[0].realized_pnl_usdt > 0
    assert len(engine.positions) == 0
    assert close_result.persisted_counts["v12_edge_estimates"] == 2
    assert close_result.persisted_counts["v12_decision_evidence"] == 2


def test_v12_decision_pipeline_refuses_missing_market_mid_without_fake_pnl(tmp_path):
    store = V12SQLiteStore(tmp_path / "v12.sqlite3")
    engine = PaperEngine(config=_cfg().paper_config)

    result = run_v12_decision_pipeline(
        V12DecisionPipelineInput(
            wallet=WALLET,
            observed_at_ms=1_700_000_000_200,
            market_mids={},
            leader_expected_edge_bps_by_coin={"HYPE": 90.0},
            run_context=RunContext.TEST_FIXTURE,
            raw_fills=(
                {
                    "coin": "HYPE",
                    "dir": "Open Short",
                    "side": "A",
                    "sz": "0.4",
                    "px": "100",
                    "time": 1_700_000_000_000,
                    "startPosition": "0",
                    "tid": "open-short",
                },
            ),
        ),
        config=_cfg(),
        paper_engine=engine,
        store=store,
    )

    assert len(result.fills) == 1
    assert result.edge_estimates[result.leader_deltas[0].delta_id].accepted is False
    assert "MID_MISSING" in result.no_trade_reasons
    assert result.paper_results[0].accepted is False
    assert result.paper_results[0].trade is not None
    assert result.paper_results[0].trade.action == "NO_TRADE"
    assert result.paper_results[0].equity_usdt == 1000.0
    assert len(engine.positions) == 0
    assert store.count("v12_decision_evidence") == 1
