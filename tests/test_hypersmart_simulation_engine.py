from __future__ import annotations

from hyper_smart_observer.simulation.simulation_engine import SimulationEngine
from hyper_smart_observer.simulation.simulation_models import (
    SimulationAction,
    SimulationConfig,
    SimulationIntent,
    SimulationSide,
)
from hyper_smart_observer.simulation.scenario_runner import run_conservative_scenario


WALLET = "0x" + "a" * 40


def intent(
    *,
    coin: str = "BTC",
    side: SimulationSide = SimulationSide.LONG,
    action: SimulationAction = SimulationAction.OPEN,
    price: float = 100.0,
    notional: float = 50.0,
    signal_id: str = "sig",
    observed_at_ms: int = 1_800_000_000_000,
) -> SimulationIntent:
    return SimulationIntent(
        wallet_address=WALLET,
        coin=coin,
        side=side,
        action=action,
        reference_price=price,
        requested_notional=notional,
        observed_at_ms=observed_at_ms,
        signal_id=signal_id,
    )


def test_simulation_starts_with_1000_and_never_orders() -> None:
    engine = SimulationEngine()

    assert engine.portfolio.starting_equity == 1000.0
    assert engine.portfolio.current_equity() == 1000.0
    assert engine.apply(intent()).accepted is True
    assert engine.decisions[-1].message.endswith("No order was created.")


def test_open_close_realizes_pnl_with_single_fee_accounting() -> None:
    engine = SimulationEngine(SimulationConfig(fee_bps=10.0, spread_bps=2.0, slippage_bps=5.0))
    assert engine.apply(intent(price=100.0, signal_id="open")).accepted
    position = next(iter(engine.portfolio.positions.values()))
    entry_price = position.entry_price
    size = position.size
    entry_fee = engine.portfolio.total_fees

    assert engine.apply(intent(action=SimulationAction.CLOSE, price=102.0, signal_id="close")).accepted
    exit_fill = engine.fills[-1]
    expected_gross = (exit_fill.price - entry_price) * size
    expected_exit_fee = exit_fill.fee

    assert engine.portfolio.positions == {}
    assert round(engine.portfolio.realized_pnl, 10) == round(expected_gross, 10)
    assert round(engine.portfolio.total_fees, 10) == round(entry_fee + expected_exit_fee, 10)
    assert round(engine.portfolio.current_equity(), 10) == round(1000.0 + expected_gross - entry_fee - expected_exit_fee, 10)


def test_reduce_virtual_position() -> None:
    engine = SimulationEngine()
    assert engine.apply(intent(price=100.0, notional=50.0, signal_id="open")).accepted
    assert engine.apply(intent(action=SimulationAction.REDUCE, price=101.0, notional=25.0, signal_id="reduce")).accepted

    position = next(iter(engine.portfolio.positions.values()))
    assert 24.0 <= position.notional <= 25.0
    assert len(engine.fills) == 2


def test_partial_fill_and_missed_fill() -> None:
    partial = SimulationEngine(SimulationConfig(partial_fill_ratio=0.5))
    assert partial.apply(intent(notional=50.0)).accepted
    position = next(iter(partial.portfolio.positions.values()))
    assert round(position.notional, 8) == 25.0

    missed = SimulationEngine(SimulationConfig(partial_fill_ratio=0.0))
    decision = missed.apply(intent(notional=50.0))
    assert decision.accepted is False
    assert decision.reason == "MISSED_FILL"


def test_caps_max_position_exposure_and_open_positions() -> None:
    engine = SimulationEngine()
    assert engine.apply(intent(coin="BTC", notional=999.0, signal_id="btc")).accepted
    assert next(iter(engine.portfolio.positions.values())).notional == 50.0
    assert engine.apply(intent(coin="ETH", signal_id="eth")).accepted
    assert engine.apply(intent(coin="SOL", signal_id="sol")).accepted
    decision = engine.apply(intent(coin="HYPE", signal_id="hype"))
    assert decision.accepted is False
    assert decision.reason == "MAX_OPEN_POSITIONS_REACHED"

    exposure = SimulationEngine(SimulationConfig(max_open_positions=10, max_total_exposure=100.0))
    assert exposure.apply(intent(coin="BTC", signal_id="btc")).accepted
    assert exposure.apply(intent(coin="ETH", signal_id="eth")).accepted
    decision = exposure.apply(intent(coin="SOL", signal_id="sol"))
    assert decision.accepted is False
    assert decision.reason == "MAX_TOTAL_EXPOSURE_REACHED"


def test_no_matching_close_and_invalid_price() -> None:
    engine = SimulationEngine()
    decision = engine.apply(intent(action=SimulationAction.CLOSE, price=100.0, signal_id="close"))
    assert decision.accepted is False
    assert decision.reason == "NO_MATCHING_VIRTUAL_POSITION"

    invalid = engine.apply(intent(price=0.0, signal_id="bad"))
    assert invalid.accepted is False
    assert invalid.reason == "PRICE_INVALID"


def test_conservative_scenario_report() -> None:
    result = run_conservative_scenario(capital=1000.0)
    assert result.engine.portfolio.starting_equity == 1000.0
    assert result.engine.portfolio.current_equity() == 1000.0
    assert len(result.engine.fills) == 0
    assert result.engine.decisions[-1].reason == "EDGE_UNPROVEN_PROTECTION_MODE"
    assert "simulate_magic_bot=local_no_money" in result.report
    assert "execution=forbidden" in result.report
