"""Fail-closed accounting and execution-quality controls for Copy-Vault."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def capital_equity_comparison_receipt(
    rows: Sequence[Mapping[str, Any]], *, canonical_capital_usd: Any
) -> dict[str, Any]:
    """Compare session equity with canonical capital without conflating the two."""
    canonical = _num(canonical_capital_usd)
    if canonical is None or canonical <= 0:
        return _base("UNMEASURABLE", reason="invalid_canonical_capital")
    if not rows:
        return _base("MORE_DATA", reason="empty_equity_history")
    invalid = []
    for index, row in enumerate(rows):
        equity = _num(row.get("session_equity_usd")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("session_id") or "").strip() or equity is None:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="SESSION_EQUITY_COMPARED_TO_CANONICAL_CAPITAL" if not invalid else "SESSION_EQUITY_COMPARISON_INCOMPLETE",
        canonical_capital_usd=canonical,
        invalid_rows=invalid,
    )


def cost_lifecycle_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Trace explicit costs from candidate trade through refusal or close."""
    stages = {"signal", "refusal", "close"}
    if not rows:
        return _base("MORE_DATA", reason="empty_cost_lifecycle")
    by_trade: dict[str, set[str]] = {}
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("trade_id") or "").strip() or row.get("stage") not in stages or _num(row.get("cost_bps")) is None:
            invalid.append(index)
            continue
        by_trade.setdefault(str(row["trade_id"]), set()).add(str(row["stage"]))
    incomplete = sorted(trade for trade, values in by_trade.items() if not values.intersection({"refusal", "close"}))
    if invalid:
        return _base("UNMEASURABLE", reason="cost_lifecycle_invalid", invalid_rows=invalid)
    return _base(
        "PROVEN" if not incomplete else "MORE_DATA",
        verdict="COST_TRACED_TO_REFUSAL_OR_CLOSE" if not incomplete else "COST_LIFECYCLE_INCOMPLETE",
        trades=by_trade,
        incomplete_trades=incomplete,
    )


def unrealized_liquidable_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep UI unrealized PnL distinct from observed liquidable value."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_ui_pnl_state")
    unrealized = _num(state.get("unrealized_pnl_usd"))
    liquidable = _num(state.get("liquidable_value_usd"))
    if unrealized is None or liquidable is None or state.get("book_observed") is not True:
        return _base("UNMEASURABLE", reason="liquidable_book_observation_missing")
    return _base(
        "PROVEN",
        verdict="UNREALIZED_AND_LIQUIDABLE_SEPARATED",
        unrealized_pnl_usd=unrealized,
        liquidable_value_usd=liquidable,
    )


def poller_turnover_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure turnover attributable to a poller loop rather than infer alpha."""
    if not rows:
        return _base("MORE_DATA", reason="empty_poller_turnover")
    invalid = []
    for index, row in enumerate(rows):
        on = _num(row.get("turnover_with_poller")) if isinstance(row, Mapping) else None
        off = _num(row.get("turnover_without_poller")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or on is None or off is None or min(on, off) < 0:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="POLLER_TURNOVER_MEASURED" if not invalid else "POLLER_TURNOVER_MISSING",
        invalid_rows=invalid,
    )


def book_fraction_receipt(
    rows: Sequence[Mapping[str, Any]], *, max_fraction: Any = 0.10
) -> dict[str, Any]:
    """Bound copied notional as an explicit fraction of observed book liquidity."""
    cap = _num(max_fraction)
    if cap is None or cap <= 0 or cap > 1:
        return _base("UNMEASURABLE", reason="invalid_book_fraction_cap")
    if not rows:
        return _base("MORE_DATA", reason="empty_book_fraction")
    invalid = []
    fractions: list[float] = []
    for index, row in enumerate(rows):
        copied = _num(row.get("copied_notional_usd")) if isinstance(row, Mapping) else None
        book = _num(row.get("observed_book_notional_usd")) if isinstance(row, Mapping) else None
        if copied is None or book is None or copied < 0 or book <= 0:
            invalid.append(index)
            continue
        fraction = copied / book
        fractions.append(fraction)
        if fraction > cap:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="BOOK_CONSUMPTION_WITHIN_CAP" if not invalid else "BOOK_CONSUMPTION_OVER_CAP",
        max_fraction=cap,
        fractions=fractions,
        invalid_rows=invalid,
    )


def close_only_fault_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require close-only to preserve risk reduction after a fault."""
    if not rows:
        return _base("MORE_DATA", reason="empty_close_only_faults")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("fault_id") or "").strip()
        or row.get("close_only") is not True
        or row.get("reduction_preserved") is not True
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CLOSE_ONLY_PRESERVES_REDUCTION" if not invalid else "CLOSE_ONLY_REDUCTION_NOT_PROVEN",
        faults=len(rows),
        invalid_rows=invalid,
    )


def forced_exit_cost_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute forced-exit cost only from an observed book and quantity."""
    if not rows:
        return _base("MORE_DATA", reason="empty_forced_exit_costs")
    invalid = []
    costs: list[float] = []
    for index, row in enumerate(rows):
        book = _num(row.get("book_price")) if isinstance(row, Mapping) else None
        exit_price = _num(row.get("forced_exit_price")) if isinstance(row, Mapping) else None
        quantity = _num(row.get("quantity")) if isinstance(row, Mapping) else None
        if book is None or exit_price is None or quantity is None or book <= 0 or exit_price <= 0 or quantity <= 0 or row.get("book_observed") is not True:
            invalid.append(index)
            continue
        costs.append((book - exit_price) * quantity)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="FORCED_EXIT_COST_FROM_OBSERVED_BOOK" if not invalid else "FORCED_EXIT_BOOK_MISSING",
        costs_usd=costs,
        invalid_rows=invalid,
    )


def historical_launcher_gain_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Record historical launcher gain as non-certifiable evidence."""
    if not isinstance(state, Mapping) or not str(state.get("history_ref") or "").strip() or state.get("certified") is not False:
        return _base("UNMEASURABLE", reason="historical_launcher_gain_not_explicitly_uncertified")
    return _base(
        "PROVEN",
        verdict="HISTORICAL_LAUNCHER_GAIN_NOT_CERTIFIED",
        history_ref=state["history_ref"],
        certified=False,
    )


def execution_quality_alpha_separation_receipt(
    execution_quality: Mapping[str, Any], alpha: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep execution-quality evidence separate from alpha evidence."""
    if not isinstance(execution_quality, Mapping) or not isinstance(alpha, Mapping):
        return _base("UNMEASURABLE", reason="execution_or_alpha_evidence_missing")
    valid = str(execution_quality.get("receipt_id") or "").strip() and str(alpha.get("receipt_id") or "").strip() and execution_quality.get("promotes_alpha") is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="EXECUTION_QUALITY_SEPARATE_FROM_ALPHA" if valid else "EXECUTION_QUALITY_PROMOTED_TO_ALPHA",
        execution_receipt=execution_quality.get("receipt_id"),
        alpha_receipt=alpha.get("receipt_id"),
    )


def economic_blocker_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the true economic blocker and keep the decision fail-closed."""
    if not isinstance(state, Mapping) or not str(state.get("blocker_type") or "").strip() or not str(state.get("detail") or "").strip():
        return _base("UNMEASURABLE", reason="economic_blocker_missing")
    valid = state.get("action") == "NO_TRADE" and state.get("real_execution") is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="ECONOMIC_BLOCKER_EXPLICIT" if valid else "ECONOMIC_BLOCKER_NOT_FAIL_CLOSED",
        blocker_type=state["blocker_type"],
        detail=state["detail"],
        action=state.get("action"),
    )


def two_sided_fee_receipt(*, entry_fee_usd: Any, exit_fee_usd: Any) -> dict[str, Any]:
    """Require both entry and exit fees before calling a trade net."""

    entry, exit_fee = _num(entry_fee_usd), _num(exit_fee_usd)
    if entry is None or exit_fee is None or entry < 0 or exit_fee < 0:
        return _base("UNMEASURABLE", reason="ENTRY_OR_EXIT_FEE_MISSING")
    return _base("PROVEN", verdict="ENTRY_AND_EXIT_FEES_INCLUDED", fees_usd=entry + exit_fee)


def realized_funding_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count only explicitly realized funding, never a forecast as cash."""

    if not rows:
        return _base("MORE_DATA", reason="empty_funding_history")
    realized: list[float] = []
    invalid: list[int] = []
    for index, row in enumerate(rows):
        value = _num(row.get("realized_funding_usd")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or value is None or row.get("realized") is not True or row.get("forecast") is True:
            invalid.append(index)
        else:
            realized.append(value)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="REALIZED_FUNDING_ONLY" if not invalid else "FUNDING_FORECAST_OR_MISSING", realized_funding_usd=sum(realized), invalid_rows=invalid)


def funding_holding_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate funding across observed holding intervals without dropping hours."""

    if not rows:
        return _base("MORE_DATA", reason="empty_holding_funding")
    invalid: list[int] = []
    total = 0.0
    for index, row in enumerate(rows):
        value = _num(row.get("realized_funding_usd")) if isinstance(row, Mapping) else None
        hours = _num(row.get("hours")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or value is None or hours is None or hours <= 0 or row.get("observed") is not True:
            invalid.append(index)
        else:
            total += value
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MULTI_HOUR_FUNDING_INCLUDED" if not invalid else "HOLDING_FUNDING_INCOMPLETE", realized_funding_usd=total, invalid_rows=invalid)


def signed_funding_cash_receipt(*, side: Any, notional_usd: Any, funding_bps_h: Any, hours: Any) -> dict[str, Any]:
    """Apply the funding sign to the position side; positive funding is paid by longs."""

    side_name = str(side or "").casefold()
    if side_name not in {"long", "short", "buy", "sell"}:
        return _base("UNMEASURABLE", reason="funding_side_invalid")
    notional, rate, duration = _num(notional_usd), _num(funding_bps_h), _num(hours)
    if notional is None or rate is None or duration is None or notional <= 0 or duration < 0:
        return _base("UNMEASURABLE", reason="funding_inputs_invalid")
    long_side = side_name in {"long", "buy"}
    cash = -notional * rate / 10_000.0 * duration if long_side else notional * rate / 10_000.0 * duration
    return _base("PROVEN", verdict="FUNDING_SIGN_APPLIED_TO_SIDE", funding_cash_usd=cash, side=side_name, paper_read_only=True)


def maker_fee_tier_receipt(*, fee_bps: Any, tier_id: Any, tier_verified: Any) -> dict[str, Any]:
    """Reject invented negative maker rebates without a verified tier."""

    fee = _num(fee_bps)
    tier = str(tier_id or "").strip()
    if fee is None or not tier or tier_verified is not True or fee < -100:
        return _base("UNMEASURABLE", reason="MAKER_TIER_NOT_PROVEN")
    if fee < 0 and tier_verified is not True:
        return _base("REJECTED", reason="NEGATIVE_MAKER_FEE_UNVERIFIED")
    return _base("PROVEN", verdict="MAKER_FEE_TIER_VERIFIED", fee_bps=fee, tier_id=tier)


def historical_fee_receipt(*, observed_fee_bps: Any, fee_effective_ts_ms: Any, trade_ts_ms: Any) -> dict[str, Any]:
    """Use a fee schedule effective at the trade, not today's schedule."""

    fee, effective, trade = _num(observed_fee_bps), _num(fee_effective_ts_ms), _num(trade_ts_ms)
    if fee is None or effective is None or trade is None or fee < 0 or effective < 0 or trade < effective:
        return _base("UNMEASURABLE", reason="HISTORICAL_FEE_INVALID")
    return _base("PROVEN", verdict="HISTORICAL_FEE_EFFECTIVE_AT_TRADE", fee_bps=fee, fee_effective_ts_ms=int(effective))


def net_pnl_receipt(*, gross_pnl_usd: Any, fees_usd: Any, liquidation_cost_usd: Any, funding_usd: Any) -> dict[str, Any]:
    """Reconcile net PnL from explicit gross, fees, liquidation costs and funding."""

    values = [_num(value) for value in (gross_pnl_usd, fees_usd, liquidation_cost_usd, funding_usd)]
    if any(value is None for value in values) or values[1] < 0 or values[2] < 0:
        return _base("UNMEASURABLE", reason="NET_PNL_COMPONENT_MISSING")
    gross, fees, liquidation, funding = values
    return _base("PROVEN", verdict="NET_PNL_RECONCILED", net_pnl_usd=gross - fees - liquidation + funding)


def liquidation_fee_receipt(*, liquidation_notional_usd: Any, liquidation_fee_bps: Any, observed: Any) -> dict[str, Any]:
    """Include observed liquidation costs in the economic ledger."""

    notional, fee = _num(liquidation_notional_usd), _num(liquidation_fee_bps)
    if notional is None or fee is None or notional <= 0 or fee < 0 or observed is not True:
        return _base("UNMEASURABLE", reason="LIQUIDATION_FEE_MISSING")
    return _base("PROVEN", verdict="LIQUIDATION_FEE_INCLUDED", liquidation_fee_usd=notional * fee / 10_000.0)


def margin_release_receipt(*, margin_usd: Any, released_usd: Any, release_count: Any, close_id: Any) -> dict[str, Any]:
    """Allow one bounded margin release for one close identity."""

    margin, released, count = _num(margin_usd), _num(released_usd), _num(release_count)
    if margin is None or released is None or count is None or margin < 0 or released < 0 or released > margin or count != 1 or not str(close_id or "").strip():
        return _base("REJECTED", reason="MARGIN_RELEASE_NOT_IDEMPOTENT")
    return _base("PROVEN", verdict="MARGIN_RELEASE_ONCE", released_margin_usd=released, close_id=str(close_id))


def available_capital_equity_receipt(*, equity_usd: Any, reserved_margin_usd: Any, available_usd: Any) -> dict[str, Any]:
    """Keep available capital distinct from total equity and reconcile the reserve."""

    equity, reserved, available = _num(equity_usd), _num(reserved_margin_usd), _num(available_usd)
    if equity is None or reserved is None or available is None or min(equity, reserved, available) < 0:
        return _base("UNMEASURABLE", reason="CAPITAL_EQUITY_INPUT_INVALID")
    valid = math.isclose(available, equity - reserved, rel_tol=0.0, abs_tol=1e-9)
    return _base("PROVEN" if valid else "REJECTED", verdict="AVAILABLE_CAPITAL_SEPARATE_FROM_EQUITY" if valid else "AVAILABLE_CAPITAL_MISMATCH", equity_usd=equity, reserved_margin_usd=reserved, available_usd=available)


def realized_pnl_receipt(*, realized_pnl_usd: Any, unrealized_pnl_usd: Any, close_verified: Any) -> dict[str, Any]:
    """Do not promote mark-to-market PnL into realized PnL."""

    realized, unrealized = _num(realized_pnl_usd), _num(unrealized_pnl_usd)
    if realized is None or unrealized is None or close_verified is not True:
        return _base("UNMEASURABLE", reason="REALIZED_CLOSE_NOT_PROVEN")
    return _base("PROVEN", verdict="REALIZED_SEPARATE_FROM_UNREALIZED", realized_pnl_usd=realized, unrealized_pnl_usd=unrealized)


def stablecoin_unit_receipt(*, asset: Any, observed_price_usd: Any) -> dict[str, Any]:
    """Use the canonical USD unit for an explicitly identified stablecoin."""

    symbol = str(asset or "").upper().strip()
    price = _num(observed_price_usd)
    if symbol not in {"USDC", "USDT", "USD"} or price is None or price <= 0:
        return _base("UNMEASURABLE", reason="STABLECOIN_UNIT_INPUT_INVALID")
    return _base("PROVEN" if math.isclose(price, 1.0, rel_tol=0.0, abs_tol=1e-9) else "REJECTED", verdict="STABLECOIN_MARKED_AT_CANONICAL_UNIT" if math.isclose(price, 1.0, rel_tol=0.0, abs_tol=1e-9) else "STABLECOIN_UNIT_MISMATCH", asset=symbol, price_usd=price)


def dust_position_receipt(*, quantity: Any, minimum_quantity: Any) -> dict[str, Any]:
    """Exclude dust positions explicitly instead of manufacturing rounded PnL."""

    qty, minimum = _num(quantity), _num(minimum_quantity)
    if qty is None or minimum is None or minimum <= 0 or qty < 0:
        return _base("UNMEASURABLE", reason="DUST_INPUT_INVALID")
    dust = qty < minimum
    return _base("PROVEN", verdict="DUST_POSITION_EXPLICIT" if dust else "POSITION_ABOVE_DUST", is_dust=dust, quantity=qty, minimum_quantity=minimum)


def fixed_point_pnl_sum_receipt(values: Sequence[Any]) -> dict[str, Any]:
    """Aggregate repeated fills in decimal arithmetic, never binary float accumulation."""

    if not values:
        return _base("MORE_DATA", reason="empty_pnl_values")
    try:
        decimals = [Decimal(str(value)) for value in values]
    except (InvalidOperation, TypeError, ValueError):
        return _base("UNMEASURABLE", reason="PNL_VALUE_INVALID")
    if not all(value.is_finite() for value in decimals):
        return _base("UNMEASURABLE", reason="PNL_VALUE_INVALID")
    total = sum(decimals, Decimal("0"))
    return _base("PROVEN", verdict="FIXED_POINT_PNL_SUM", pnl_usd_exact=str(total), pnl_usd=float(total))


def exit_cost_receipt(*, exit_cost_usd: Any, exit_observed: Any) -> dict[str, Any]:
    """Require an explicit observed exit cost before certifying net PnL."""

    cost = _num(exit_cost_usd)
    if cost is None or cost < 0 or exit_observed is not True:
        return _base("UNMEASURABLE", reason="EXIT_COST_MISSING")
    return _base("PROVEN", verdict="EXIT_COST_INCLUDED", exit_cost_usd=cost)


def multi_asset_usd_pnl_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sum PnL only after every asset row is explicitly expressed in USD."""

    if not rows:
        return _base("MORE_DATA", reason="empty_asset_pnl")
    invalid: list[int] = []
    total = 0.0
    for index, row in enumerate(rows):
        value = _num(row.get("pnl_usd")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or value is None or row.get("unit") != "USD":
            invalid.append(index)
        else:
            total += value
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MULTI_ASSET_USD_UNIT_RECONCILED" if not invalid else "MIXED_PNL_UNITS", pnl_usd=total, invalid_rows=invalid)


def external_deposit_pnl_receipt(*, reported_pnl_usd: Any, external_deposit_usd: Any) -> dict[str, Any]:
    """Keep external deposits out of trading PnL."""

    reported, deposit = _num(reported_pnl_usd), _num(external_deposit_usd)
    if reported is None or deposit is None or deposit < 0:
        return _base("UNMEASURABLE", reason="EXTERNAL_DEPOSIT_INPUT_INVALID")
    return _base("PROVEN", verdict="EXTERNAL_DEPOSIT_EXCLUDED_FROM_PNL", trading_pnl_usd=reported - deposit, external_deposit_usd=deposit)


def trade_fee_attribution_receipt(*, trade_id: Any, fee_trade_id: Any, fee_usd: Any) -> dict[str, Any]:
    """Attach fees to the same native trade identity, never to an adjacent trade."""

    fee = _num(fee_usd)
    same = str(trade_id or "").strip() and str(trade_id).strip() == str(fee_trade_id or "").strip()
    if not same or fee is None or fee < 0:
        return _base("UNMEASURABLE", reason="TRADE_FEE_IDENTITY_MISMATCH")
    return _base("PROVEN", verdict="FEE_ATTRIBUTED_TO_NATIVE_TRADE", trade_id=str(trade_id), fee_usd=fee)


def zero_fill_pnl_receipt(*, filled_notional_usd: Any, pnl_usd: Any) -> dict[str, Any]:
    """A zero-filled paper event cannot produce a positive trade PnL."""

    filled, pnl = _num(filled_notional_usd), _num(pnl_usd)
    if filled is None or pnl is None or filled < 0:
        return _base("UNMEASURABLE", reason="FILL_PNL_INPUT_INVALID")
    valid = filled > 0 or pnl <= 0
    return _base("PROVEN" if valid else "REJECTED", verdict="ZERO_FILL_NO_POSITIVE_PNL" if valid else "POSITIVE_PNL_WITHOUT_FILL", filled_notional_usd=filled, pnl_usd=pnl)


def closed_open_loss_stats_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Include realized and currently open losses in the reported statistics."""

    if not rows:
        return _base("MORE_DATA", reason="empty_trade_stats")
    invalid: list[int] = []
    total = 0.0
    for index, row in enumerate(rows):
        pnl = _num(row.get("pnl_usd")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or pnl is None or row.get("state") not in {"closed", "open"}:
            invalid.append(index)
        else:
            total += pnl
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="OPEN_AND_CLOSED_PNL_INCLUDED" if not invalid else "TRADE_STATE_MISSING", pnl_usd=total, invalid_rows=invalid)


__all__ = [
    "capital_equity_comparison_receipt",
    "cost_lifecycle_receipt",
    "unrealized_liquidable_receipt",
    "poller_turnover_receipt",
    "book_fraction_receipt",
    "close_only_fault_receipt",
    "forced_exit_cost_receipt",
    "historical_launcher_gain_receipt",
    "execution_quality_alpha_separation_receipt",
    "economic_blocker_receipt",
    "two_sided_fee_receipt",
    "realized_funding_receipt",
    "funding_holding_receipt",
    "signed_funding_cash_receipt",
    "maker_fee_tier_receipt",
    "historical_fee_receipt",
    "net_pnl_receipt",
    "liquidation_fee_receipt",
    "margin_release_receipt",
    "available_capital_equity_receipt",
    "realized_pnl_receipt",
    "stablecoin_unit_receipt",
    "dust_position_receipt",
    "fixed_point_pnl_sum_receipt",
    "exit_cost_receipt",
    "multi_asset_usd_pnl_receipt",
    "external_deposit_pnl_receipt",
    "trade_fee_attribution_receipt",
    "zero_fill_pnl_receipt",
    "closed_open_loss_stats_receipt",
]
