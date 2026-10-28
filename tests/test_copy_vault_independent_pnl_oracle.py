from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext

import pytest

from hl_observer.simulation.paper_event import PaperEvent, PaperEventType
from hl_observer.simulation.paper_ledger import LedgerPosition, PaperLedger


class OracleEvidenceError(ValueError):
    def __init__(self, event_seq: int, field: str, reason: str) -> None:
        self.event_seq = event_seq
        self.field = field
        super().__init__(f"event={event_seq} field={field} reason={reason}")


def _decimal(value: object, *, event_seq: int, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise OracleEvidenceError(event_seq, field, "UNKNOWN_OR_INVALID")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OracleEvidenceError(event_seq, field, "INVALID_DECIMAL") from exc
    if not result.is_finite():
        raise OracleEvidenceError(event_seq, field, "NON_FINITE")
    return result


def _recompute_paper_events(
    events: list[dict[str, object]],
    *,
    starting_cash_usdc: object,
    max_reference_age_ms: int,
) -> dict[str, object]:
    """Independent Decimal oracle; deliberately does not call ledger/math helpers."""
    if isinstance(max_reference_age_ms, bool) or not isinstance(max_reference_age_ms, int) or max_reference_age_ms <= 0:
        raise ValueError("max_reference_age_ms must be a positive integer")
    epsilon = Decimal("0.00000001")
    cash = _decimal(starting_cash_usdc, event_seq=0, field="starting_cash_usdc")
    if cash <= 0:
        raise OracleEvidenceError(0, "starting_cash_usdc", "NOT_POSITIVE")
    fees = Decimal(0)
    funding = Decimal(0)
    realized = Decimal(0)
    last_unrealized = Decimal(0)
    high_water = cash
    drawdown = Decimal(0)
    positions: dict[str, dict[str, object]] = {}
    fee_events: dict[str, tuple[Decimal, int]] = {}
    used_fee_event_ids: set[str] = set()
    funding_settlement_ids: set[str] = set()
    event_ids: set[str] = set()
    previous_timestamp = 0
    last_event_timestamp = 0
    max_reconciliation_error_usdc = Decimal(0)
    reconciliation_comparison_count = 0

    def add(*values: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 100
            return sum(values, Decimal(0))

    def product(left: Decimal, right: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 100
            return left * right

    def quotient(numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            raise OracleEvidenceError(0, "denominator", "ZERO")
        with localcontext() as context:
            context.prec = 100
            return numerator / denominator

    def equal(actual: Decimal, expected: Decimal, *, event_seq: int, field: str) -> None:
        nonlocal max_reconciliation_error_usdc, reconciliation_comparison_count
        difference = add(actual, -expected)
        max_reconciliation_error_usdc = max(max_reconciliation_error_usdc, abs(difference))
        reconciliation_comparison_count += 1
        if abs(difference) > epsilon:
            raise OracleEvidenceError(event_seq, field, f"MISMATCH expected={expected} actual={actual}")

    def validate_fill_metadata(
        refs: Mapping[str, object], quantity: Decimal, *, event_seq: int
    ) -> None:
        requested_value = refs.get("requested_quantity")
        if requested_value is None:
            if any(key in refs for key in ("filled_quantity", "fill_ratio", "partial_fill")):
                raise OracleEvidenceError(event_seq, "requested_quantity", "MISSING")
            return
        requested = _decimal(requested_value, event_seq=event_seq, field="requested_quantity")
        if requested <= 0 or quantity <= 0 or quantity > requested:
            raise OracleEvidenceError(event_seq, "requested_quantity", "INVALID_OR_FILLED_EXCEEDS_REQUEST")
        if "filled_quantity" in refs:
            equal(
                _decimal(refs.get("filled_quantity"), event_seq=event_seq, field="filled_quantity"),
                quantity, event_seq=event_seq, field="filled_quantity",
            )
        expected_ratio = quotient(quantity, requested)
        if "fill_ratio" in refs:
            equal(
                _decimal(refs.get("fill_ratio"), event_seq=event_seq, field="fill_ratio"),
                expected_ratio, event_seq=event_seq, field="fill_ratio",
            )
        if "partial_fill" in refs:
            partial_fill = refs.get("partial_fill")
            if not isinstance(partial_fill, bool) or partial_fill != (quantity < requested):
                raise OracleEvidenceError(event_seq, "partial_fill", "MISMATCH")

    for index, row in enumerate(events, start=1):
        event_seq_value = row.get("event_seq")
        if isinstance(event_seq_value, bool):
            raise OracleEvidenceError(index, "event_seq", "INVALID")
        event_seq = index if event_seq_value is None else int(event_seq_value)
        if event_seq != index:
            raise OracleEvidenceError(event_seq, "event_seq", "NON_CONTIGUOUS")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids:
            raise OracleEvidenceError(event_seq, "event_id", "MISSING_OR_DUPLICATE")
        event_ids.add(event_id)
        timestamp = row.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise OracleEvidenceError(event_seq, "timestamp_ms", "INVALID")
        if timestamp < previous_timestamp:
            raise OracleEvidenceError(event_seq, "timestamp_ms", "OUT_OF_ORDER")
        previous_timestamp = timestamp
        last_event_timestamp = timestamp
        event_type = row.get("event_type")
        refs = row.get("refs")
        if not isinstance(refs, Mapping):
            raise OracleEvidenceError(event_seq, "refs", "MISSING")

        if event_type == PaperEventType.FEE_CHARGED.value:
            amount = _decimal(row.get("fee_usdc"), event_seq=event_seq, field="fee_usdc")
            if amount < 0:
                raise OracleEvidenceError(event_seq, "fee_usdc", "NEGATIVE")
            currency = str(refs.get("fee_currency") or "USDC").upper()
            if currency != "USDC":
                native_fee = _decimal(refs.get("native_fee_amount"), event_seq=event_seq, field="native_fee_amount")
                conversion = _decimal(refs.get("fee_to_usdc_rate"), event_seq=event_seq, field="fee_to_usdc_rate")
                conversion_ts = refs.get("fee_conversion_timestamp_ms")
                source = refs.get("fee_conversion_source")
                if (
                    native_fee < 0 or conversion <= 0
                    or isinstance(conversion_ts, bool) or not isinstance(conversion_ts, int)
                    or conversion_ts <= 0 or conversion_ts > timestamp
                    or not isinstance(source, str) or not source.strip()
                ):
                    raise OracleEvidenceError(event_seq, "fee_conversion_timestamp_ms", "MISSING_STALE_OR_UNSOURCED")
                if timestamp - conversion_ts > max_reference_age_ms:
                    raise OracleEvidenceError(event_seq, "fee_conversion_timestamp_ms", "STALE")
                equal(product(native_fee, conversion), amount, event_seq=event_seq, field="fee_usdc")
            fees = add(fees, amount)
            cash = add(cash, -amount)
            fee_events[event_id] = (amount, event_seq)
            continue

        if event_type in (PaperEventType.FUNDING_RECEIVED.value, PaperEventType.FUNDING_CHARGED.value):
            amount = _decimal(row.get("funding_usdc"), event_seq=event_seq, field="funding_usdc")
            settlement_id = refs.get("funding_settlement_id")
            if not isinstance(settlement_id, str) or not settlement_id.strip():
                raise OracleEvidenceError(event_seq, "funding_settlement_id", "UNKNOWN")
            if settlement_id in funding_settlement_ids:
                raise OracleEvidenceError(event_seq, "funding_settlement_id", "DUPLICATE")
            funding_settlement_ids.add(settlement_id)
            if (event_type == PaperEventType.FUNDING_RECEIVED.value and amount < 0) or (
                event_type == PaperEventType.FUNDING_CHARGED.value and amount > 0
            ):
                raise OracleEvidenceError(event_seq, "funding_usdc", "SIGN_CONTRADICTS_EVENT_TYPE")
            funding = add(funding, amount)
            cash = add(cash, amount)
            continue

        if event_type in (PaperEventType.POSITION_OPENED.value, PaperEventType.POSITION_INCREASED.value):
            position_id = refs.get("position_id")
            if not isinstance(position_id, str) or not position_id:
                raise OracleEvidenceError(event_seq, "position_id", "MISSING")
            fee_id = refs.get("fee_event_id")
            if not isinstance(fee_id, str) or fee_id not in fee_events:
                raise OracleEvidenceError(event_seq, "fee_event_id", "MISSING_OR_NOT_PREVIOUS")
            if fee_id in used_fee_event_ids:
                raise OracleEvidenceError(event_seq, "fee_event_id", "REUSED")
            used_fee_event_ids.add(fee_id)
            event_fee = _decimal(row.get("fee_usdc"), event_seq=event_seq, field="fee_usdc")
            equal(event_fee, fee_events[fee_id][0], event_seq=event_seq, field="fee_usdc")
            quantity = _decimal(row.get("quantity"), event_seq=event_seq, field="quantity")
            price = _decimal(row.get("price"), event_seq=event_seq, field="price")
            notional = _decimal(row.get("notional_usdc"), event_seq=event_seq, field="notional_usdc")
            validate_fill_metadata(refs, quantity, event_seq=event_seq)
            if quantity <= 0 or price <= 0:
                raise OracleEvidenceError(event_seq, "quantity/price", "NOT_POSITIVE")
            equal(product(quantity, price), notional, event_seq=event_seq, field="notional_usdc")
            side = str(row.get("side") or "").upper()
            if side not in ("LONG", "SHORT"):
                raise OracleEvidenceError(event_seq, "side", "INVALID")
            coin = row.get("coin")
            if not isinstance(coin, str) or not coin:
                raise OracleEvidenceError(event_seq, "coin", "MISSING")
            old = positions.get(position_id)
            if event_type == PaperEventType.POSITION_OPENED.value:
                if old is not None:
                    raise OracleEvidenceError(event_seq, "position_id", "OPEN_ALREADY_EXISTS")
                average = price
            else:
                if old is None:
                    raise OracleEvidenceError(event_seq, "position_id", "ADD_WITHOUT_OPEN")
                if old["side"] != side or old["coin"] != coin:
                    raise OracleEvidenceError(event_seq, "side/coin", "IDENTITY_CHANGED")
                old_quantity = old["quantity"]
                old_average = old["average"]
                if not isinstance(old_quantity, Decimal) or not isinstance(old_average, Decimal):
                    raise OracleEvidenceError(event_seq, "position_state", "INVALID")
                total_quantity = add(old_quantity, quantity)
                average = quotient(add(product(old_quantity, old_average), product(quantity, price)), total_quantity)
                quantity = total_quantity
            positions[position_id] = {
                "coin": coin, "side": side, "quantity": quantity,
                "average": average, "mark": price,
                "mark_timestamp_ms": None, "mark_source": None,
            }
            continue

        if event_type in (PaperEventType.POSITION_REDUCED.value, PaperEventType.POSITION_CLOSED.value):
            position_id = refs.get("position_id")
            if not isinstance(position_id, str) or position_id not in positions:
                raise OracleEvidenceError(event_seq, "position_id", "CLOSE_WITHOUT_OPEN")
            fee_id = refs.get("fee_event_id")
            if not isinstance(fee_id, str) or fee_id not in fee_events:
                raise OracleEvidenceError(event_seq, "fee_event_id", "MISSING_OR_NOT_PREVIOUS")
            if fee_id in used_fee_event_ids:
                raise OracleEvidenceError(event_seq, "fee_event_id", "REUSED")
            used_fee_event_ids.add(fee_id)
            equal(
                _decimal(row.get("fee_usdc"), event_seq=event_seq, field="fee_usdc"),
                fee_events[fee_id][0], event_seq=event_seq, field="fee_usdc",
            )
            position = positions[position_id]
            quantity = _decimal(row.get("quantity"), event_seq=event_seq, field="quantity")
            price = _decimal(row.get("price"), event_seq=event_seq, field="price")
            notional = _decimal(row.get("notional_usdc"), event_seq=event_seq, field="notional_usdc")
            validate_fill_metadata(refs, quantity, event_seq=event_seq)
            equal(product(quantity, price), notional, event_seq=event_seq, field="notional_usdc")
            old_quantity = position["quantity"]
            average = position["average"]
            side = position["side"]
            if not isinstance(old_quantity, Decimal) or not isinstance(average, Decimal) or side not in ("LONG", "SHORT"):
                raise OracleEvidenceError(event_seq, "position_state", "INVALID")
            if quantity <= 0 or quantity > old_quantity or row.get("side") != side:
                raise OracleEvidenceError(event_seq, "quantity/side", "CLOSE_INVALID")
            signed_move = add(price, -average) if side == "LONG" else add(average, -price)
            gross = product(signed_move, quantity)
            event_realized = _decimal(row.get("realized_pnl_usdc"), event_seq=event_seq, field="realized_pnl_usdc")
            equal(gross, event_realized, event_seq=event_seq, field="realized_pnl_usdc")
            realized = add(realized, gross)
            cash = add(cash, gross)
            remaining = add(old_quantity, -quantity)
            if remaining <= 0:
                positions.pop(position_id)
            else:
                position["quantity"] = remaining
                position["mark"] = price
            continue

        if event_type == PaperEventType.EQUITY_UPDATED.value:
            if refs.get("mark_evidence_complete") is not True:
                raise OracleEvidenceError(event_seq, "mark_evidence_complete", "UNKNOWN")
            marks = refs.get("marks")
            if not isinstance(marks, Mapping):
                raise OracleEvidenceError(event_seq, "marks", "MISSING")
            mark_timestamps = refs.get("mark_timestamps_ms")
            mark_sources = refs.get("mark_sources")
            if not isinstance(mark_timestamps, Mapping):
                raise OracleEvidenceError(event_seq, "mark_timestamps_ms", "MISSING")
            if not isinstance(mark_sources, Mapping):
                raise OracleEvidenceError(event_seq, "mark_sources", "MISSING")
            unrealized_values: list[Decimal] = []
            for position_id, position in positions.items():
                coin = position["coin"]
                if not isinstance(coin, str) or coin not in marks:
                    raise OracleEvidenceError(event_seq, f"marks.{coin}", "MISSING")
                mark_timestamp = mark_timestamps.get(coin)
                mark_source = mark_sources.get(coin)
                if (
                    isinstance(mark_timestamp, bool)
                    or not isinstance(mark_timestamp, int)
                    or mark_timestamp <= 0
                    or mark_timestamp > timestamp
                    or not isinstance(mark_source, str)
                    or not mark_source.strip()
                ):
                    raise OracleEvidenceError(event_seq, f"mark_timestamps_ms.{coin}", "MISSING_FUTURE_OR_UNSOURCED")
                if timestamp - mark_timestamp > max_reference_age_ms:
                    raise OracleEvidenceError(event_seq, f"mark_timestamps_ms.{coin}", "STALE")
                mark = _decimal(marks[coin], event_seq=event_seq, field=f"marks.{coin}")
                if mark <= 0:
                    raise OracleEvidenceError(event_seq, f"marks.{coin}", "NOT_POSITIVE")
                quantity = position["quantity"]
                average = position["average"]
                side = position["side"]
                if not isinstance(quantity, Decimal) or not isinstance(average, Decimal):
                    raise OracleEvidenceError(event_seq, f"positions.{position_id}", "INVALID")
                move = add(mark, -average) if side == "LONG" else add(average, -mark)
                unrealized_values.append(product(move, quantity))
                position["mark"] = mark
                position["mark_timestamp_ms"] = mark_timestamp
                position["mark_source"] = mark_source
            last_unrealized = add(*unrealized_values)
            equity = add(cash, last_unrealized)
            high_water = max(high_water, equity)
            drawdown = add(high_water, -equity)
            equal(_decimal(row.get("unrealized_pnl_usdc"), event_seq=event_seq, field="unrealized_pnl_usdc"), last_unrealized, event_seq=event_seq, field="unrealized_pnl_usdc")
            equal(_decimal(row.get("equity_usdc"), event_seq=event_seq, field="equity_usdc"), equity, event_seq=event_seq, field="equity_usdc")
            equal(_decimal(row.get("drawdown_usdc"), event_seq=event_seq, field="drawdown_usdc"), drawdown, event_seq=event_seq, field="drawdown_usdc")
            continue

        if event_type == PaperEventType.NO_TRADE.value:
            for field in (
                "quantity", "notional_usdc", "fee_usdc", "funding_usdc",
                "realized_pnl_usdc", "unrealized_pnl_usdc",
            ):
                amount = _decimal(row.get(field), event_seq=event_seq, field=field)
                if amount != 0:
                    raise OracleEvidenceError(event_seq, field, "NONZERO_NO_TRADE_EVENT")
            continue

        raise OracleEvidenceError(event_seq, "event_type", "UNSUPPORTED")

    for position_id, position in positions.items():
        mark_timestamp = position.get("mark_timestamp_ms")
        if isinstance(mark_timestamp, bool) or not isinstance(mark_timestamp, int) or mark_timestamp <= 0:
            raise OracleEvidenceError(
                len(events), f"positions.{position_id}.mark_timestamp_ms", "MISSING"
            )
        if last_event_timestamp - mark_timestamp > max_reference_age_ms:
            raise OracleEvidenceError(
                len(events), f"positions.{position_id}.mark_timestamp_ms", "STALE"
            )

    final_equity = add(cash, last_unrealized)
    return {
        "cash_usdc": cash,
        "fees_usdc": fees,
        "funding_usdc": funding,
        "realized_pnl_usdc": realized,
        "unrealized_pnl_usdc": last_unrealized,
        "equity_usdc": final_equity,
        "drawdown_usdc": drawdown,
        "max_reconciliation_error_usdc": max_reconciliation_error_usdc,
        "reconciliation_comparison_count": reconciliation_comparison_count,
        "positions": {
            key: {field: str(value) if isinstance(value, Decimal) else value for field, value in position.items()}
            for key, position in positions.items()
        },
    }


def _fixture_ledger() -> PaperLedger:
    before_midnight = int(datetime(2026, 10, 27, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
    after_midnight = int(datetime(2026, 10, 28, 0, 0, 1, tzinfo=UTC).timestamp() * 1000)
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="independent-oracle")

    ledger.open_position(
        coin="BTC", side="LONG", notional_usdc=100.0, quantity=1.0,
        fill_price=100.0, timestamp_ms=before_midnight, fee_bps=5.0,
        position_id="copy:long",
        refs={"requested_quantity": "1.0", "filled_quantity": "1.0", "fill_ratio": "1.0", "partial_fill": False},
    )
    ledger.mark_to_market({"BTC": 101.0}, timestamp_ms=before_midnight + 500)
    ledger.open_position(
        coin="BTC", side="LONG", notional_usdc=55.0, quantity=0.5,
        fill_price=110.0, timestamp_ms=after_midnight, fee_bps=5.0,
        position_id="copy:long",
        refs={"requested_quantity": "0.75", "filled_quantity": "0.5", "fill_ratio": "0.6666666666666667", "partial_fill": True},
    )
    ledger.apply_funding(
        coin="BTC", side="LONG", amount_usdc=0.1, timestamp_ms=after_midnight + 100,
        refs={"funding_settlement_id": "BTC:2026-10-28T00:00:00Z"},
    )
    ledger.mark_to_market({"BTC": 108.0}, timestamp_ms=after_midnight + 200)
    ledger.reduce_or_close(
        coin="BTC", side="LONG", quantity=0.5, fill_price=108.0,
        timestamp_ms=after_midnight + 300, fee_bps=5.0, position_id="copy:long",
        refs={"requested_quantity": "1.0", "filled_quantity": "0.5", "fill_ratio": "0.5", "partial_fill": True},
    )
    ledger.reduce_or_close(
        coin="BTC", side="LONG", quantity=1.0, fill_price=99.0,
        timestamp_ms=after_midnight + 400, fee_bps=5.0, position_id="copy:long",
    )

    ledger.open_position(
        coin="ETH", side="SHORT", notional_usdc=100.0, quantity=2.0,
        fill_price=50.0, timestamp_ms=after_midnight + 500, fee_bps=5.0,
        position_id="copy:short",
    )
    ledger.mark_to_market({"ETH": 48.0}, timestamp_ms=after_midnight + 600)
    ledger.apply_funding(
        coin="ETH", side="SHORT", amount_usdc=-0.2, timestamp_ms=after_midnight + 700,
        refs={"funding_settlement_id": "ETH:2026-10-28T00:00:01Z"},
    )
    ledger.reduce_or_close(
        coin="ETH", side="SHORT", quantity=1.0, fill_price=55.0,
        timestamp_ms=after_midnight + 800, fee_bps=5.0, position_id="copy:short",
    )
    ledger.reduce_or_close(
        coin="ETH", side="SHORT", quantity=1.0, fill_price=52.0,
        timestamp_ms=after_midnight + 900, fee_bps=5.0, position_id="copy:short",
    )
    return ledger


def _raw_event_dicts(ledger: PaperLedger) -> list[dict[str, object]]:
    return [event.to_dict() for event in ledger.events]


def _event_dicts(ledger: PaperLedger) -> list[dict[str, object]]:
    """Add explicit deterministic source metadata to synthetic mark fixtures."""
    events = _raw_event_dicts(ledger)
    for row in events:
        if row["event_type"] != PaperEventType.EQUITY_UPDATED.value:
            continue
        refs = row["refs"]
        if not isinstance(refs, dict):
            continue
        marks = refs.get("marks")
        if not isinstance(marks, Mapping):
            continue
        refs["mark_timestamps_ms"] = {
            coin: row["timestamp_ms"] for coin in marks
        }
        refs["mark_sources"] = {coin: "fixture:causal-book" for coin in marks}
    return events


def test_independent_oracle_reconciles_long_short_add_partial_close_funding_and_equity() -> None:
    ledger = _fixture_ledger()

    result = _recompute_paper_events(
        _event_dicts(ledger), starting_cash_usdc=ledger.starting_balance_usdc,
        max_reference_age_ms=2_000,
    )
    snapshot = ledger.snapshot()

    for oracle_key, ledger_key in (
        ("cash_usdc", "cash_balance_usdc"),
        ("realized_pnl_usdc", "realized_pnl_usdc"),
        ("fees_usdc", "fees_paid_usdc"),
        ("funding_usdc", "funding_net_usdc"),
        ("unrealized_pnl_usdc", "unrealized_pnl_usdc"),
        ("equity_usdc", "equity_usdc"),
        ("drawdown_usdc", "drawdown_usdc"),
    ):
        assert abs(Decimal(str(snapshot[ledger_key])) - result[oracle_key]) <= Decimal("0.00000001")
    assert result["positions"] == {}
    assert abs(result["realized_pnl_usdc"] - Decimal("-9")) <= Decimal("1e-25")
    assert result["funding_usdc"] == Decimal("-0.1")


def test_oracle_reports_first_event_and_field_on_divergent_mark() -> None:
    events = _event_dicts(_fixture_ledger())
    mark = next(row for row in events if row["event_type"] == PaperEventType.EQUITY_UPDATED.value)
    mark["equity_usdc"] = float(mark["equity_usdc"]) + 0.01

    with pytest.raises(OracleEvidenceError, match="field=equity_usdc") as error:
        _recompute_paper_events(events, starting_cash_usdc=1_000.0, max_reference_age_ms=2_000)

    assert error.value.event_seq == mark["event_seq"]


def test_oracle_reconciles_requested_vs_partial_filled_quantity() -> None:
    events = _event_dicts(_fixture_ledger())
    partial = next(
        row for row in events
        if row["event_type"] == PaperEventType.POSITION_INCREASED.value
    )
    partial["refs"]["filled_quantity"] = "0.49"  # type: ignore[index]

    with pytest.raises(OracleEvidenceError, match="field=filled_quantity") as error:
        _recompute_paper_events(
            events, starting_cash_usdc=1_000.0, max_reference_age_ms=2_000
        )

    assert error.value.event_seq == partial["event_seq"]


def test_oracle_blocks_missing_or_nonfinite_evidence_instead_of_using_zero() -> None:
    events = _event_dicts(_fixture_ledger())
    mark = next(row for row in events if row["event_type"] == PaperEventType.EQUITY_UPDATED.value)
    mark["refs"]["marks"] = {}  # type: ignore[index]

    with pytest.raises(OracleEvidenceError, match="field=marks.BTC"):
        _recompute_paper_events(events, starting_cash_usdc=1_000.0, max_reference_age_ms=2_000)

    events = _event_dicts(_fixture_ledger())
    funding = next(row for row in events if row["event_type"] == PaperEventType.FUNDING_RECEIVED.value)
    funding["funding_usdc"] = float("nan")
    with pytest.raises(OracleEvidenceError, match="field=funding_usdc"):
        _recompute_paper_events(events, starting_cash_usdc=1_000.0, max_reference_age_ms=2_000)

    events = _event_dicts(_fixture_ledger())
    events[0]["event_type"] = "PaperEconomicEventUnknown"
    with pytest.raises(OracleEvidenceError, match="field=event_type"):
        _recompute_paper_events(events, starting_cash_usdc=1_000.0, max_reference_age_ms=2_000)


def test_oracle_rejects_missing_or_stale_point_in_time_marks() -> None:
    ledger = _fixture_ledger()
    missing = _raw_event_dicts(ledger)
    with pytest.raises(OracleEvidenceError, match="field=mark_timestamps_ms"):
        _recompute_paper_events(
            missing, starting_cash_usdc=ledger.starting_balance_usdc,
            max_reference_age_ms=2_000,
        )

    stale = _event_dicts(ledger)
    mark = next(row for row in stale if row["event_type"] == PaperEventType.EQUITY_UPDATED.value)
    mark_ts = mark["timestamp_ms"]
    mark["refs"]["mark_timestamps_ms"]["BTC"] = mark_ts - 2_001  # type: ignore[index]
    with pytest.raises(OracleEvidenceError, match="field=mark_timestamps_ms.BTC reason=STALE"):
        _recompute_paper_events(
            stale, starting_cash_usdc=ledger.starting_balance_usdc,
            max_reference_age_ms=2_000,
        )

    open_ledger = PaperLedger(starting_balance_usdc=200.0, session_id="stale-final-mark")
    opened = open_ledger.open_position(
        coin="BTC", side="LONG", notional_usdc=100.0, quantity=1.0,
        fill_price=100.0, timestamp_ms=1_800_000_000_000, fee_bps=0.0,
        position_id="copy:open",
    )
    open_ledger.mark_to_market({"BTC": 100.0}, timestamp_ms=opened.timestamp_ms)
    open_ledger.no_trade(
        coin="BTC", reason="fixture heartbeat",
        timestamp_ms=opened.timestamp_ms + 2_001,
    )
    with pytest.raises(OracleEvidenceError, match="field=positions.copy:open.mark_timestamp_ms reason=STALE"):
        _recompute_paper_events(
            _event_dicts(open_ledger), starting_cash_usdc=200.0,
            max_reference_age_ms=2_000,
        )


def test_oracle_validates_point_in_time_multicurrency_fee_conversion() -> None:
    event = PaperEvent.create(
        PaperEventType.FEE_CHARGED,
        timestamp_ms=1_800_000_000_000,
        fee_usdc=0.202,
        refs={
            "position_id": "fee:fx",
            "fee_currency": "USDT",
            "native_fee_amount": "0.2",
            "fee_to_usdc_rate": "1.01",
            "fee_conversion_timestamp_ms": 1_799_999_999_000,
            "fee_conversion_source": "fixture:point-in-time-index",
        },
    )

    result = _recompute_paper_events(
        [event.to_dict()], starting_cash_usdc=200.0, max_reference_age_ms=2_000
    )

    assert result["fees_usdc"] == Decimal("0.202")
    assert result["cash_usdc"] == Decimal("199.798")

    stale = event.to_dict()
    stale["refs"]["fee_conversion_timestamp_ms"] = event.timestamp_ms - 2_001  # type: ignore[index]
    with pytest.raises(OracleEvidenceError, match="field=fee_conversion_timestamp_ms"):
        _recompute_paper_events([stale], starting_cash_usdc=200.0, max_reference_age_ms=2_000)


def test_oracle_does_not_call_the_ledger_calculation_path(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _fixture_ledger()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ledger calculation path was called")

    monkeypatch.setattr(PaperLedger, "snapshot", forbidden)
    monkeypatch.setattr(LedgerPosition, "unrealized", forbidden)

    result = _recompute_paper_events(
        _event_dicts(ledger), starting_cash_usdc=ledger.starting_balance_usdc,
        max_reference_age_ms=2_000,
    )
    serialized = json.dumps(
        {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()},
        allow_nan=False,
        sort_keys=True,
    )
    assert Decimal(str(result["cash_usdc"])).quantize(Decimal("0.0001")) == Decimal("990.6425")
    assert serialized == json.dumps(
        {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()},
        allow_nan=False,
        sort_keys=True,
    )


def test_oracle_replays_256_closed_round_trips_stably_at_high_event_depth() -> None:
    def make_ledger() -> PaperLedger:
        ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="precision-256-round-trips")
        base_ts = 1_800_000_000_000
        for index in range(256):
            timestamp = base_ts + index * 10
            side = "LONG" if index % 2 == 0 else "SHORT"
            entry = 100.0 + index / 100.0
            exit_price = entry + 0.05
            position_id = f"copy:round-trip:{index}"
            opened = ledger.open_position(
                coin="BTC", side=side, notional_usdc=entry, quantity=1.0,
                fill_price=entry, timestamp_ms=timestamp, fee_bps=5.0,
                position_id=position_id,
            )
            assert opened.event_type == PaperEventType.POSITION_OPENED
            closed = ledger.reduce_or_close(
                coin="BTC", side=side, quantity=1.0, fill_price=exit_price,
                timestamp_ms=timestamp + 1, fee_bps=5.0,
                position_id=position_id,
            )
            assert closed.event_type == PaperEventType.POSITION_CLOSED
        return ledger

    ledger_a = make_ledger()
    ledger_b = make_ledger()
    events_a = _event_dicts(ledger_a)
    events_b = _event_dicts(ledger_b)
    assert len(events_a) == len(events_b) == 1_280

    oracle_a = _recompute_paper_events(
        events_a, starting_cash_usdc=ledger_a.starting_balance_usdc,
        max_reference_age_ms=2_000,
    )
    oracle_b = _recompute_paper_events(
        events_b, starting_cash_usdc=ledger_b.starting_balance_usdc,
        max_reference_age_ms=2_000,
    )

    serialized_a = json.dumps(
        {key: str(value) if isinstance(value, Decimal) else value for key, value in oracle_a.items()},
        allow_nan=False, sort_keys=True,
    )
    serialized_b = json.dumps(
        {key: str(value) if isinstance(value, Decimal) else value for key, value in oracle_b.items()},
        allow_nan=False, sort_keys=True,
    )
    assert serialized_a == serialized_b
    ledger_events_a = json.dumps(events_a, allow_nan=False, sort_keys=True, separators=(",", ":"))
    ledger_events_b = json.dumps(events_b, allow_nan=False, sort_keys=True, separators=(",", ":"))
    assert ledger_events_a == ledger_events_b
    round_tripped_events = json.loads(ledger_events_a)
    oracle_after_json_round_trip = _recompute_paper_events(
        round_tripped_events,
        starting_cash_usdc=ledger_a.starting_balance_usdc,
        max_reference_age_ms=2_000,
    )
    assert oracle_after_json_round_trip == oracle_a
    assert oracle_a["positions"] == {}
    assert oracle_a["reconciliation_comparison_count"] >= len(events_a)
    assert oracle_a["max_reconciliation_error_usdc"] <= Decimal("0.00000001")
    snapshot = ledger_a.snapshot()
    assert abs(Decimal(str(snapshot["equity_usdc"])) - oracle_a["equity_usdc"]) <= Decimal("0.00000001")
    assert abs(Decimal(str(snapshot["fees_paid_usdc"])) - oracle_a["fees_usdc"]) <= Decimal("0.00000001")
    assert abs(Decimal(str(snapshot["realized_pnl_usdc"])) - oracle_a["realized_pnl_usdc"]) <= Decimal("0.00000001")
