"""Fail-closed robustness controls for Copy-Vault research evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def aggregate_result_receipt(*, trade_count: Any, independent_episode_count: Any, bootstrap_sample_count: Any, aggregate_required: bool) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) and value > 1 for value in (trade_count, independent_episode_count, bootstrap_sample_count)) and independent_episode_count <= trade_count and bool(aggregate_required)
    return _base("PROVEN" if valid else "REJECTED", verdict="AGGREGATE_EVIDENCE_REQUIRED" if valid else "SINGLE_TRADE_OR_NO_AGGREGATION", trade_count=trade_count, independent_episode_count=independent_episode_count, bootstrap_sample_count=bootstrap_sample_count, fail_closed=not valid)


def hindsight_budget_receipt(*, allocation_ts_ms: Any, outcome_cutoff_ms: Any, allocation_frozen: bool) -> dict[str, Any]:
    valid = isinstance(allocation_ts_ms, int) and not isinstance(allocation_ts_ms, bool) and isinstance(outcome_cutoff_ms, int) and not isinstance(outcome_cutoff_ms, bool) and allocation_ts_ms <= outcome_cutoff_ms and bool(allocation_frozen)
    return _base("PROVEN" if valid else "REJECTED", verdict="BUDGET_PRE_OUTCOME_FROZEN" if valid else "BUDGET_HINDSIGHT", allocation_ts_ms=allocation_ts_ms, outcome_cutoff_ms=outcome_cutoff_ms, allocation_frozen=bool(allocation_frozen), fail_closed=not valid)


def price_error_margin_receipt(*, net_gain_usd: Any, price_error_usd: Any) -> dict[str, Any]:
    try:
        gain = float(net_gain_usd); error = float(price_error_usd)
        valid = math.isfinite(gain) and math.isfinite(error) and error >= 0.0 and gain > error
    except (TypeError, ValueError, OverflowError):
        gain = error = None; valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="GAIN_EXCEEDS_PRICE_ERROR" if valid else "GAIN_WITHIN_PRICE_ERROR", net_gain_usd=gain if valid else None, price_error_usd=error if valid else None, fail_closed=not valid)


def cost_sweep_receipt(*, scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not scenarios:
        return _base("MORE_DATA", reason="empty_cost_sweep")
    labels = {str(row.get("scenario") or "").strip().casefold() for row in scenarios if isinstance(row, Mapping)}
    finite = True
    for row in scenarios:
        try:
            finite = finite and isinstance(row, Mapping) and math.isfinite(float(row.get("net_pnl_usd")))
        except (TypeError, ValueError, OverflowError):
            finite = False
    valid = finite and bool(labels & {"adverse", "worst_case", "pessimistic"})
    return _base("PROVEN" if valid else "REJECTED", verdict="COST_SWEEP_INCLUDES_ADVERSE" if valid else "COST_SWEEP_FAVORABLE_ONLY", scenarios=len(scenarios), labels=sorted(labels), fail_closed=not valid)


def variance_disclosure_receipt(*, values: Sequence[Any], variance_reported: bool) -> dict[str, Any]:
    try:
        parsed = [float(value) for value in values]
        mean = sum(parsed) / len(parsed)
        variance = sum((value - mean) ** 2 for value in parsed) / (len(parsed) - 1)
        valid = len(parsed) >= 2 and all(math.isfinite(value) for value in parsed) and math.isfinite(variance) and bool(variance_reported)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        mean = variance = None; valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="VARIANCE_DISCLOSED" if valid else "VARIANCE_HIDDEN", sample_count=len(values), mean=mean if valid else None, sample_variance=variance if valid else None, fail_closed=not valid)


def survivorship_wallet_receipt(*, included_wallets: Sequence[Any], exited_wallets: Sequence[Any], leaderboard_includes_exited: bool) -> dict[str, Any]:
    included = {str(value) for value in included_wallets}; exited = {str(value) for value in exited_wallets}
    valid = bool(included) and bool(leaderboard_includes_exited) and bool(exited)
    return _base("PROVEN" if valid else "REJECTED", verdict="SURVIVORSHIP_CONTROLLED" if valid else "SURVIVORSHIP_BIAS", included_wallets=sorted(included), exited_wallets=sorted(exited), fail_closed=not valid)


def regime_shift_stress_receipt(*, available_regimes: Sequence[Any], tested_regimes: Sequence[Any], stress_loss_limit_usd: Any) -> dict[str, Any]:
    try:
        limit = float(stress_loss_limit_usd); available = {str(value) for value in available_regimes}; tested = {str(value) for value in tested_regimes}
        valid = bool(available) and available.issubset(tested) and math.isfinite(limit) and limit >= 0.0
    except (TypeError, ValueError, OverflowError):
        limit = None; available = tested = set(); valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="REGIME_SHIFT_STRESSED" if valid else "REGIME_SHIFT_UNTESTED", available_regimes=sorted(available), tested_regimes=sorted(tested), stress_loss_limit_usd=limit if valid else None, fail_closed=not valid)


def stop_loss_causality_receipt(*, trigger_ts_ms: Any, observed_quote_ts_ms: Any, outcome_ts_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (trigger_ts_ms, observed_quote_ts_ms, outcome_ts_ms)) and observed_quote_ts_ms <= trigger_ts_ms <= outcome_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="STOP_LOSS_CAUSAL" if valid else "STOP_LOSS_FUTURE_DATA", trigger_ts_ms=trigger_ts_ms, observed_quote_ts_ms=observed_quote_ts_ms, outcome_ts_ms=outcome_ts_ms, fail_closed=not valid)


def liquidation_closure_receipt(*, position_ids: Sequence[Any], closed_position_ids: Sequence[Any], liquidation_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positions = {str(value) for value in position_ids}; closed = {str(value) for value in closed_position_ids}; event_ids = {str(row.get("position_id")) for row in liquidation_events if isinstance(row, Mapping) and str(row.get("position_id") or "").strip()}
    valid = bool(positions) and positions.issubset(closed) and positions.issubset(event_ids)
    return _base("PROVEN" if valid else "REJECTED", verdict="LIQUIDATION_POSITIONS_CLOSED" if valid else "LIQUIDATION_POSITION_OPEN", position_count=len(positions), closed_count=len(closed), event_count=len(event_ids), fail_closed=not valid)


def holdout_reuse_receipt(*, holdout_id: Any, consumed_holdout_ids: Sequence[Any], reuse_blocked: bool) -> dict[str, Any]:
    holdout = str(holdout_id).strip(); consumed = {str(value).strip() for value in consumed_holdout_ids if str(value).strip()}
    valid = bool(holdout) and (holdout not in consumed or bool(reuse_blocked))
    return _base("PROVEN" if valid else "REJECTED", verdict="HOLDOUT_REUSE_BLOCKED" if valid else "HOLDOUT_REUSED", holdout_id=holdout, consumed=holdout in consumed, reuse_blocked=bool(reuse_blocked), fail_closed=not valid)


__all__ = ["aggregate_result_receipt", "hindsight_budget_receipt", "price_error_margin_receipt", "cost_sweep_receipt", "variance_disclosure_receipt", "survivorship_wallet_receipt", "regime_shift_stress_receipt", "stop_loss_causality_receipt", "liquidation_closure_receipt", "holdout_reuse_receipt"]
