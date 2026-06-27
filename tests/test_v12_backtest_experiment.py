from __future__ import annotations

from hl_observer.backtesting.experiment import (
    BacktestExperimentConfig,
    PriceTick,
    run_paper_replay_experiment,
)
from hl_observer.paper_trading.paper_engine import PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


WALLET = "0x" + "c" * 40


def _delta(action: LifecycleAction, previous: float, current: float, observed: int) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"ld:bt:{action.value}:{observed}",
        wallet=WALLET,
        coin="HYPE",
        action=action,
        previous_size=previous,
        current_size=current,
        delta_size=current - previous,
        observed_at_ms=observed,
        leader_event_time_ms=observed - 100,
        source="backtest_unit",
        confidence=0.95,
        evidence_ref=f"fill:{observed}",
    )


def test_v12_backtest_uses_first_tick_after_decision_no_lookahead():
    result = run_paper_replay_experiment(
        deltas=[_delta(LifecycleAction.OPEN_LONG, 0, 1, 1_000)],
        price_ticks=[
            PriceTick("HYPE", 900, 90.0, "too_early"),
            PriceTick("HYPE", 1_050, 100.0, "first_after"),
            PriceTick("HYPE", 2_000, 110.0, "later"),
        ],
        config=BacktestExperimentConfig(latency_ms=50, paper=PaperEngineConfig(max_position_usdt=40.0)),
    )

    assert result.decisions[0].accepted
    assert result.decisions[0].fill_tick_time_ms == 1_050
    assert result.evidence[0].source_refs == ("leader_delta", "first_after", "paper_engine")
    assert result.warning == "historical result is not future profit"


def test_v12_backtest_open_and_close_realizes_local_pnl():
    result = run_paper_replay_experiment(
        deltas=[
            _delta(LifecycleAction.OPEN_LONG, 0, 1, 1_000),
            _delta(LifecycleAction.CLOSE_LONG, 1, 0, 2_000),
        ],
        price_ticks=[
            PriceTick("HYPE", 1_000, 100.0, "entry_tick"),
            PriceTick("HYPE", 2_000, 105.0, "exit_tick"),
        ],
        config=BacktestExperimentConfig(latency_ms=0, paper=PaperEngineConfig(max_position_usdt=40.0, default_top_depth_usdt=100_000.0)),
    )

    assert [decision.accepted for decision in result.decisions] == [True, True]
    assert result.realized_pnl_usdt > 0
    assert result.final_equity_usdt > 1000.0
    assert result.evidence[-1].paper_trade_id is not None


def test_v12_backtest_skips_when_no_future_price_tick():
    result = run_paper_replay_experiment(
        deltas=[_delta(LifecycleAction.OPEN_SHORT, 0, -1, 2_000)],
        price_ticks=[PriceTick("HYPE", 1_999, 100.0, "before_only")],
        config=BacktestExperimentConfig(latency_ms=1),
    )

    assert result.decisions[0].accepted is False
    assert result.decisions[0].stopped_reason == "NO_FUTURE_PRICE_TICK"
    assert result.skipped_no_future_price == 1
    assert result.evidence == ()
