from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.config.settings import Settings
from hl_observer.copying import PaperSimulationDecision, run_paper_simulation_decision
from hl_observer.features import MarketFeatureVector
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.storage.run_context import RunContext, RunContextScope, build_run_context_scope, may_merge_pnl


@dataclass(frozen=True, slots=True)
class RuntimeReplayParityResult:
    runtime_scope: RunContextScope
    replay_scope: RunContextScope
    runtime_decision: PaperSimulationDecision
    replay_decision: PaperSimulationDecision
    economics_match: bool
    risk_match: bool
    pnl_may_merge: bool
    warnings: tuple[str, ...]


def compare_runtime_replay_paper(
    *,
    signal: SignalCandidate,
    market: MarketFeatureVector | None,
    settings: Settings | None = None,
    notional_usdc: float = 100.0,
    runtime_run_id: str = "live-paper",
    replay_run_id: str = "replay-paper",
) -> RuntimeReplayParityResult:
    """Compare deterministic paper economics between live simulation and replay.

    The two contexts intentionally do not merge PnL. The comparison verifies
    that identical read-only inputs produce identical paper economics and risk
    decisions, while their run namespaces remain isolated.
    """

    if (isinstance(notional_usdc, bool) or not math.isfinite(float(notional_usdc))
            or float(notional_usdc) <= 0.0):
        raise ValueError("notional_usdc must be finite and > 0")
    if not str(runtime_run_id).strip() or not str(replay_run_id).strip():
        raise ValueError("run ids are required")
    settings = settings or Settings()
    runtime_scope = build_run_context_scope(RunContext.LIVE, run_id=runtime_run_id)
    replay_scope = build_run_context_scope(RunContext.REPLAY, run_id=replay_run_id)
    runtime_decision = run_paper_simulation_decision(
        signal=signal,
        market=market,
        settings=settings,
        executor=PaperExecutor(),
        run_id=runtime_scope.run_id,
        notional_usdc=notional_usdc,
    )
    replay_decision = run_paper_simulation_decision(
        signal=signal,
        market=market,
        settings=settings,
        executor=PaperExecutor(),
        run_id=replay_scope.run_id,
        notional_usdc=notional_usdc,
    )
    economics_match = _paper_economics_tuple(runtime_decision) == _paper_economics_tuple(replay_decision)
    risk_match = _risk_tuple(runtime_decision) == _risk_tuple(replay_decision)
    pnl_may_merge = may_merge_pnl(runtime_scope, replay_scope)
    warnings: list[str] = []
    if not economics_match:
        warnings.append("PAPER_ECONOMICS_DIVERGED")
    if not risk_match:
        warnings.append("RISK_DECISION_DIVERGED")
    if pnl_may_merge:
        warnings.append("PNL_CONTEXT_UNEXPECTEDLY_MERGEABLE")
    return RuntimeReplayParityResult(
        runtime_scope=runtime_scope,
        replay_scope=replay_scope,
        runtime_decision=runtime_decision,
        replay_decision=replay_decision,
        economics_match=economics_match,
        risk_match=risk_match,
        pnl_may_merge=pnl_may_merge,
        warnings=tuple(warnings),
    )


def _paper_economics_tuple(decision: PaperSimulationDecision) -> tuple:
    order = decision.paper_order
    return (
        order.coin,
        order.side,
        round(order.notional_usdc, 12),
        round(order.requested_price, 12),
        round(order.simulated_fill_price, 12),
        round(order.fee_bps, 12),
        round(order.slippage_bps, 12),
        order.rejected_reason,
    )


def _risk_tuple(decision: PaperSimulationDecision) -> tuple:
    risk = decision.risk_decision
    return (
        risk.allowed,
        getattr(risk.decision, "value", str(risk.decision)),
        tuple(risk.reasons),
        tuple(sorted(risk.gates.items())),
    )


def _parity_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _parity_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parity_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def runtime_parity_safety_receipt(result: Any) -> dict[str, Any]:
    valid = isinstance(result, RuntimeReplayParityResult) and result.economics_match is True and result.risk_match is True and result.pnl_may_merge is False and not result.warnings
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="RUNTIME_REPLAY_PARITY_SAFE" if valid else "RUNTIME_REPLAY_PARITY_UNSAFE", fail_closed=not valid)


def parity_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_FIELD_PRESENT" if valid else "PARITY_FIELD_MISSING", field=field, fail_closed=not valid)


def parity_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_FIELD_NON_NULL" if valid else "PARITY_FIELD_NULL", field=field, fail_closed=not valid)


def parity_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_FIELD_TYPE_VALID" if valid else "PARITY_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def parity_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _parity_finite(value)
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_VALUE_FINITE" if valid else "PARITY_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def parity_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _parity_integer(event_ts_ms) and _parity_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_EVENT_WITHIN_CUTOFF" if valid else "PARITY_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def parity_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _parity_integer(event_ts_ms) and _parity_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_EVENT_AGE_VALID" if valid else "PARITY_EVENT_TOO_OLD", fail_closed=not valid)


def parity_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_EVENTS_UNIQUE" if valid else "PARITY_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def parity_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _parity_integer(attempts) and _parity_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_RETRY_BOUNDED" if valid else "PARITY_RETRY_UNSAFE", fail_closed=not valid)


def parity_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_REPLAY_DETERMINISTIC" if valid else "PARITY_REPLAY_DIVERGED", fail_closed=not valid)


def parity_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_FILLS_UNIQUE" if valid else "PARITY_FILL_DUPLICATED", fail_closed=not valid)


def parity_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_REJECTION_NO_DEBIT" if valid else "PARITY_REJECTION_DEBITED", fail_closed=not valid)


def parity_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = float(close_quantity) if _parity_finite(close_quantity) else None
    open_size = float(open_quantity) if _parity_finite(open_quantity) else None
    fee = float(fee_amount) if _parity_finite(fee_amount) else None
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_PARTIAL_CLOSE_COSTED" if valid else "PARITY_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def parity_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = float(close_quantity) if _parity_finite(close_quantity) else None
    open_size = float(open_quantity) if _parity_finite(open_quantity) else None
    release = float(released_margin) if _parity_finite(released_margin) else None
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_TOTAL_CLOSE_RELEASED" if valid else "PARITY_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def parity_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = float(mark_price) if _parity_finite(mark_price) else None
    best_bid = float(bid) if _parity_finite(bid) else None
    best_ask = float(ask) if _parity_finite(ask) else None
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_MARK_LIQUIDABLE" if valid else "PARITY_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def parity_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _parity_finite(balance) else None
    valid = value is not None and value >= 0
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_BALANCE_NON_NEGATIVE" if valid else "PARITY_BALANCE_NEGATIVE", fail_closed=not valid)


def parity_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _parity_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_FUNDING_SIGN_VALID" if valid else "PARITY_FUNDING_SIGN_INVALID", fail_closed=not valid)


def parity_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _parity_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _parity_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_CONVERSION_PROVEN" if valid else "PARITY_CONVERSION_MISSING", fail_closed=not valid)


def parity_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_COMMIT_ATOMIC" if valid else "PARITY_COMMIT_PARTIAL", fail_closed=not valid)


def parity_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _parity_base("PROVEN" if valid else "REJECTED", verdict="PARITY_WRITES_UNIQUE" if valid else "PARITY_DOUBLE_WRITE", fail_closed=not valid)


__all__ = [
    "RuntimeReplayParityResult", "compare_runtime_replay_paper",
    "runtime_parity_safety_receipt", "parity_required_field_receipt", "parity_null_field_receipt",
    "parity_field_type_receipt", "parity_finite_receipt", "parity_cutoff_receipt", "parity_age_receipt",
    "parity_duplicate_receipt", "parity_retry_receipt", "parity_replay_receipt", "parity_fill_duplicate_receipt",
    "parity_rejection_no_debit_receipt", "parity_partial_close_receipt", "parity_total_close_release_receipt",
    "parity_mark_liquidability_receipt", "parity_balance_receipt", "parity_funding_sign_receipt",
    "parity_conversion_receipt", "parity_commit_receipt", "parity_concurrent_write_receipt",
]
