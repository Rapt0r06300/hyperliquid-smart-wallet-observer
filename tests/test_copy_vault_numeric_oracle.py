"""Independent Decimal oracle for the canonical paper ledger's money path.

The venue-native price/size precision belongs to its point-in-time instrument
metadata. This oracle starts from exact decimal fill inputs, independently
calculates linear-contract notional, gross PnL and half-even fee rounding to
the canonical ledger's current 10-decimal USDC aggregate precision, then
measures cumulative deviation across a deterministic event sequence. It does
not certify strategy profitability.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from hl_observer.economics.numeric import float_not_above, float_not_below
from hl_observer.simulation.ledger_integrity import canonical_json
from hl_observer.simulation.paper_event import PaperEventType
from hl_observer.simulation.paper_ledger import PaperLedger

_Q10 = Decimal("0.0000000001")
_FEE_BPS = Decimal("4.5")


def test_float_serialization_rounds_pnl_and_cost_in_conservative_directions() -> None:
    source = Decimal("0.10000000000000001")

    assert Decimal(str(float_not_above(source))) <= source
    assert Decimal(str(float_not_below(source))) >= source


def _q10(value: Decimal) -> Decimal:
    return value.quantize(_Q10, rounding=ROUND_HALF_EVEN)


def _fee(notional: Decimal) -> Decimal:
    return _q10(notional * _FEE_BPS / Decimal(10_000))


def _replay_decimal_oracle_and_ledger(
    *, edge_improvement: Decimal = Decimal("0")
) -> tuple[
    PaperLedger, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal
]:
    ledger = PaperLedger(starting_balance_usdc=200.0, session_id="numeric-oracle")
    oracle_cash = Decimal("200")
    oracle_realized = Decimal("0")
    oracle_fees = Decimal("0")
    oracle_funding = Decimal("0")
    peak_equity = Decimal("200")
    maximum_equity_error = Decimal("0")
    maximum_drawdown_error = Decimal("0")

    for index in range(256):
        quantity = Decimal("0.100") + Decimal(index % 7) / Decimal("1000")
        entry = Decimal("99.50000") + Decimal((index * 13) % 31) / Decimal("10000")
        mode = index % 4
        if mode == 0:
            side, exit_price = "LONG", entry  # fee-only round trip
        elif mode == 1:
            side, exit_price = "LONG", entry + Decimal("0.02000") + edge_improvement
        elif mode == 2:
            side, exit_price = "SHORT", entry - Decimal("0.05000") - edge_improvement
        else:
            side, exit_price = "SHORT", entry + Decimal("0.01000") - edge_improvement

        entry_notional = quantity * entry
        exit_notional = quantity * exit_price
        entry_fee = _fee(entry_notional)
        exit_fee = _fee(exit_notional)
        gross = (
            (exit_price - entry) * quantity
            if side == "LONG"
            else (entry - exit_price) * quantity
        )

        timestamp_ms = 1_000 + index * 3
        opened = ledger.open_position(
            coin="BTC",
            side=side,
            notional_usdc=float(entry_notional),
            quantity=float(quantity),
            fill_price=float(entry),
            timestamp_ms=timestamp_ms,
            fee_bps=float(_FEE_BPS),
            position_id=f"oracle-position-{index}",
        )
        assert opened.reason is None

        if index % 7 == 0:
            funding_magnitude = _q10(entry_notional * Decimal("0.0001"))
            funding = -funding_magnitude if side == "LONG" else funding_magnitude
            settled = ledger.apply_funding(
                coin="BTC",
                side=side,
                amount_usdc=float(funding),
                timestamp_ms=timestamp_ms + 1,
                refs={"funding_settlement_id": f"BTC:oracle:{index}"},
            )
            assert settled.event_type in {
                PaperEventType.FUNDING_RECEIVED,
                PaperEventType.FUNDING_CHARGED,
            }
            oracle_cash = _q10(oracle_cash + funding)
            oracle_funding = _q10(oracle_funding + funding)

        closed = ledger.reduce_or_close(
            coin="BTC",
            side=side,
            quantity=float(quantity),
            fill_price=float(exit_price),
            timestamp_ms=timestamp_ms + 2,
            fee_bps=float(_FEE_BPS),
            position_id=f"oracle-position-{index}",
        )
        assert closed.event_type == PaperEventType.POSITION_CLOSED

        oracle_cash = _q10(oracle_cash - entry_fee)
        oracle_fees = _q10(oracle_fees + entry_fee)
        oracle_realized = _q10(oracle_realized + gross)
        oracle_cash = _q10(oracle_cash + gross)
        oracle_cash = _q10(oracle_cash - exit_fee)
        oracle_fees = _q10(oracle_fees + exit_fee)
        peak_equity = max(peak_equity, oracle_cash)

        equity_error = abs(Decimal(str(ledger.equity_usdc)) - oracle_cash)
        drawdown = max(Decimal("0"), peak_equity - oracle_cash)
        drawdown_error = abs(Decimal(str(ledger.drawdown_usdc)) - drawdown)
        maximum_equity_error = max(maximum_equity_error, equity_error)
        maximum_drawdown_error = max(maximum_drawdown_error, drawdown_error)

    assert ledger.verify_event_chain()
    assert ledger.snapshot()["strict_pnl_allowed"] is True
    return (
        ledger,
        oracle_cash,
        oracle_realized,
        oracle_fees,
        oracle_funding,
        maximum_equity_error,
        maximum_drawdown_error,
    )


def test_decimal_oracle_bounds_long_replay_and_preserves_negative_net_pnl() -> None:
    (
        ledger,
        expected_cash,
        expected_realized,
        expected_fees,
        expected_funding,
        maximum_equity_error,
        maximum_drawdown_error,
    ) = (
        _replay_decimal_oracle_and_ledger()
    )

    # This fixed deterministic replay has a large negative margin to zero; a
    # numeric representation error must not turn it into a profitable result.
    tolerance = Decimal("0.000001")
    actual_cash = Decimal(str(ledger.cash_balance_usdc))
    actual_realized = Decimal(str(ledger.realized_pnl_usdc))
    actual_fees = Decimal(str(ledger.fees_paid_usdc))
    actual_funding = Decimal(str(ledger.funding_net_usdc))
    actual_net = actual_cash - Decimal("200")
    expected_net = expected_cash - Decimal("200")

    assert expected_net < Decimal("-1")
    assert expected_funding != 0
    assert actual_net < 0
    assert abs(actual_cash - expected_cash) <= tolerance
    assert abs(actual_realized - expected_realized) <= tolerance
    assert abs(actual_fees - expected_fees) <= tolerance
    assert abs(actual_funding - expected_funding) <= tolerance
    assert abs(actual_net - expected_net) <= tolerance
    assert maximum_equity_error <= tolerance
    assert maximum_drawdown_error <= tolerance


def test_decimal_oracle_replay_serialization_is_deterministic() -> None:
    first, *_ = _replay_decimal_oracle_and_ledger()
    second, *_ = _replay_decimal_oracle_and_ledger()

    first_rows = [event.to_dict() for event in first.events]
    second_rows = [event.to_dict() for event in second.events]
    assert canonical_json(first_rows) == canonical_json(second_rows)


def test_decimal_oracle_error_bound_cannot_invert_separated_candidate_rank() -> None:
    baseline, baseline_expected_cash, *_ = _replay_decimal_oracle_and_ledger()
    challenger, challenger_expected_cash, *_ = _replay_decimal_oracle_and_ledger(
        edge_improvement=Decimal("0.001")
    )
    tolerance = Decimal("0.000001")
    expected_gap = challenger_expected_cash - baseline_expected_cash
    actual_gap = Decimal(str(challenger.cash_balance_usdc)) - Decimal(
        str(baseline.cash_balance_usdc)
    )

    assert expected_gap > 2 * tolerance
    assert actual_gap > 0
    assert abs(actual_gap - expected_gap) <= 2 * tolerance
