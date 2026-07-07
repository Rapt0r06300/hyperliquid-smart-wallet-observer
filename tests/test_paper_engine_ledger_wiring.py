from __future__ import annotations

from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.ui.state import UiState
from hl_observer.ui.status_routes import _paper_ledger_projection_from_status_state


WALLET = "0x" + "d" * 40


def _delta(action: LifecycleAction, previous: float, current: float, ts: int) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"ld:ledger:{action.value}:{previous}:{current}:{ts}",
        wallet=WALLET,
        coin="HYPE",
        action=action,
        previous_size=previous,
        current_size=current,
        delta_size=current - previous,
        observed_at_ms=ts + 100,
        leader_event_time_ms=ts,
        source="unit_test",
        confidence=0.95,
        evidence_ref=f"fill:{ts}",
    )


def _apply(engine: PaperEngine, delta: LeaderDelta, price: float):
    return engine.apply_delta(
        delta,
        market_price=price,
        observed_at_ms=delta.observed_at_ms,
        edge_remaining_bps=90.0,
        spread_bps=1.0,
        estimated_slippage_bps=1.0,
        top_depth_usdt=1_000_000.0,
        wallet_score=95.0,
        signal_score=90.0,
        marks={"HYPE": price},
    )


def test_paper_engine_writes_canonical_ledger_for_open_and_close() -> None:
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=100.0, default_top_depth_usdt=1_000_000.0))

    opened = _apply(engine, _delta(LifecycleAction.OPEN_LONG, 0.0, 1.0, 1_700_000_000_000), 100.0)

    assert opened.accepted
    assert opened.ledger_snapshot is not None
    assert opened.ledger_snapshot["reconciliation"]["ok"] is True
    assert "HYPE:LONG" in opened.ledger_snapshot["positions"]
    assert any(event.refs.get("embedded_cost_model") for event in engine.ledger.events)

    closed = _apply(engine, _delta(LifecycleAction.CLOSE_LONG, 1.0, 0.0, 1_700_000_010_000), 102.0)

    assert closed.accepted
    assert closed.trade is not None
    assert closed.trade.action == "CLOSE"
    assert closed.ledger_snapshot is not None
    assert closed.ledger_snapshot["positions"] == {}
    assert closed.ledger_snapshot["reconciliation"]["ok"] is True
    assert abs(float(closed.ledger_snapshot["realized_pnl_usdc"]) - closed.realized_pnl_usdt) < 1e-8


def test_status_paper_ledger_projection_reconciles_and_flags_large_jumps() -> None:
    state = UiState()
    state.simulation_ledger_events = [
        {"paper_action_type": "OPEN", "observed_at_ms": 1},
        {"paper_action_type": "CLOSE", "observed_at_ms": 2},
    ]
    state.simulation_equity_history = [
        {"timestamp_ms": 1, "current_equity_usdt": 1000.0, "source": "SESSION_START"},
        {"timestamp_ms": 2, "current_equity_usdt": 1001.1, "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"},
    ]
    state.simulation_entry_costs_paid_usdc = 0.25
    marked = {
        "realized_pnl_usdc": 0.4,
        "unrealized_pnl_usdc": 0.7,
        "current_equity_usdt": 1001.1,
        "positions": [{"coin": "HYPE"}],
    }

    projection = _paper_ledger_projection_from_status_state(
        state=state,
        starting_equity_usdt=1000.0,
        marked=marked,
        current_ms=3,
    )

    assert projection["reconciliation"]["ok"] is True
    assert projection["event_count"] == 2
    assert projection["event_counts"]["OPEN"] == 1
    assert projection["legacy_costs_reported_usdc"] == 0.25
    assert projection["spike_diagnostics"]["spike_count"] == 1
    assert projection["spike_diagnostics"]["interpretation"] == "CHECK_LEDGER_EVENTS_AROUND_SPIKES"
