"""Explicit capital, margin, exposure and ROI semantics for paper trading."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PositionCapitalInput:
    position_id: str
    leg_notional_usd: tuple[float, ...]
    leg_direction: tuple[int, ...]
    leverage_effective: float
    unrealized_mid_pnl_usd: float
    liquidatable_pnl_usd: float | None
    liquidation_buffer_bps: float | None = None

    def __post_init__(self) -> None:
        if not self.position_id:
            raise ValueError("position_id is required")
        if not self.leg_notional_usd:
            raise ValueError("at least one leg notional is required")
        if len(self.leg_notional_usd) != len(self.leg_direction):
            raise ValueError("leg notional and direction lengths differ")
        if any(not _finite_positive(value) for value in self.leg_notional_usd):
            raise ValueError("leg notionals must be finite and positive")
        if any(direction not in {-1, 1} for direction in self.leg_direction):
            raise ValueError("leg directions must be -1 or 1")
        if not _finite_positive(self.leverage_effective):
            raise ValueError("leverage_effective must be finite and positive")
        if not _finite(self.unrealized_mid_pnl_usd):
            raise ValueError("unrealized_mid_pnl_usd must be finite")
        if self.liquidatable_pnl_usd is not None and not _finite(
            self.liquidatable_pnl_usd
        ):
            raise ValueError("liquidatable_pnl_usd must be finite or None")
        if self.liquidation_buffer_bps is not None and not _finite(
            self.liquidation_buffer_bps
        ):
            raise ValueError("liquidation_buffer_bps must be finite or None")

    @property
    def gross_exposure_usd(self) -> float:
        return sum(abs(value) for value in self.leg_notional_usd)

    @property
    def net_directional_exposure_usd(self) -> float:
        return sum(
            value * direction
            for value, direction in zip(
                self.leg_notional_usd,
                self.leg_direction,
                strict=True,
            )
        )

    @property
    def margin_locked_usd(self) -> float:
        return self.gross_exposure_usd / self.leverage_effective


@dataclass(frozen=True, slots=True)
class CapitalAccountingSnapshot:
    starting_equity_usd: float
    free_cash_usd: float
    margin_locked_usd: float
    gross_exposure_usd: float
    net_directional_exposure_usd: float
    leg_notional_usd: tuple[float, ...]
    leverage_effective: float | None
    liquidation_buffer_bps: float | None
    realized_pnl_usd: float
    unrealized_mid_pnl_usd: float
    liquidatable_pnl_usd: float | None
    mid_equity_usd: float
    liquidatable_equity_usd: float | None
    turnover_usd: float
    avg_margin_locked_usd: float
    peak_margin_locked_usd: float
    ROI_starting_equity: float | None
    ROI_avg_margin_locked: float | None
    ROI_peak_margin_locked: float | None
    return_on_gross_exposure: float | None
    roi_status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["leg_notional_usd"] = list(self.leg_notional_usd)
        return payload


class CapitalAccountingTracker:
    """Track comparable paper-capital denominators across observations."""

    def __init__(self, *, starting_equity_usd: float) -> None:
        if not _finite_positive(starting_equity_usd):
            raise ValueError("starting_equity_usd must be finite and positive")
        self.starting_equity_usd = float(starting_equity_usd)
        self._margin_sum = 0.0
        self._margin_observations = 0
        self._peak_margin = 0.0
        self._last_observed_margin: float | None = None
        self._latest: CapitalAccountingSnapshot | None = None

    @property
    def latest(self) -> CapitalAccountingSnapshot | None:
        return self._latest

    def observe(
        self,
        *,
        collateral_cash_usd: float,
        positions: tuple[PositionCapitalInput, ...],
        realized_pnl_usd: float,
        turnover_usd: float,
    ) -> CapitalAccountingSnapshot:
        for name, value in (
            ("collateral_cash_usd", collateral_cash_usd),
            ("realized_pnl_usd", realized_pnl_usd),
            ("turnover_usd", turnover_usd),
        ):
            if not _finite(value):
                raise ValueError(f"{name} must be finite")
        gross = sum(position.gross_exposure_usd for position in positions)
        net = sum(position.net_directional_exposure_usd for position in positions)
        margin = sum(position.margin_locked_usd for position in positions)
        mid_pnl = sum(position.unrealized_mid_pnl_usd for position in positions)
        for name, value in (
            ("gross_exposure_usd", gross),
            ("net_directional_exposure_usd", net),
            ("margin_locked_usd", margin),
            ("unrealized_mid_pnl_usd", mid_pnl),
        ):
            if not _finite(value):
                raise ValueError(f"{name} aggregate must be finite")
        liquidatable_known = all(
            position.liquidatable_pnl_usd is not None for position in positions
        )
        liquidatable_pnl = (
            sum(float(position.liquidatable_pnl_usd or 0.0) for position in positions)
            if liquidatable_known
            else None
        )
        if liquidatable_pnl is not None and not _finite(liquidatable_pnl):
            raise ValueError("liquidatable_pnl_usd aggregate must be finite")
        cash = float(collateral_cash_usd)
        free_cash = cash - margin
        mid_equity = cash + mid_pnl
        liquidatable_equity = (
            cash + liquidatable_pnl if liquidatable_pnl is not None else None
        )
        authoritative_pnl = (
            liquidatable_equity - self.starting_equity_usd
            if liquidatable_equity is not None
            else None
        )
        for name, value in (
            ("free_cash_usd", free_cash),
            ("mid_equity_usd", mid_equity),
            ("liquidatable_equity_usd", liquidatable_equity),
            ("authoritative_pnl_usd", authoritative_pnl),
        ):
            if value is not None and not _finite(value):
                raise ValueError(f"{name} must be finite")
        # Average active margin is sampled only on capital state changes. It is
        # therefore deterministic and does not change when the UI or mark loop
        # polls more frequently.
        next_margin_sum = self._margin_sum
        next_margin_observations = self._margin_observations
        next_last_observed_margin = self._last_observed_margin
        if margin > 0 and (
            self._last_observed_margin is None
            or not math.isclose(
                margin,
                self._last_observed_margin,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            next_margin_observations += 1
            next_margin_sum += margin
            next_last_observed_margin = margin
        if not _finite(next_margin_sum):
            raise ValueError("avg_margin_locked_usd accumulator must be finite")
        next_peak_margin = max(self._peak_margin, margin)
        average_margin = (
            next_margin_sum / next_margin_observations
            if next_margin_observations
            else 0.0
        )
        if not _finite(average_margin) or not _finite(next_peak_margin):
            raise ValueError("margin summary must be finite")
        leverage = gross / margin if margin > 0 else None
        if leverage is not None and not _finite(leverage):
            raise ValueError("leverage_effective must be finite")
        buffers = [
            float(position.liquidation_buffer_bps)
            for position in positions
            if position.liquidation_buffer_bps is not None
        ]
        snapshot = CapitalAccountingSnapshot(
            starting_equity_usd=round(self.starting_equity_usd, 10),
            free_cash_usd=round(free_cash, 10),
            margin_locked_usd=round(margin, 10),
            gross_exposure_usd=round(gross, 10),
            net_directional_exposure_usd=round(net, 10),
            leg_notional_usd=tuple(
                round(value, 10)
                for position in positions
                for value in position.leg_notional_usd
            ),
            leverage_effective=round(leverage, 10) if leverage is not None else None,
            liquidation_buffer_bps=min(buffers) if len(buffers) == len(positions) and buffers else None,
            realized_pnl_usd=round(float(realized_pnl_usd), 10),
            unrealized_mid_pnl_usd=round(mid_pnl, 10),
            liquidatable_pnl_usd=(
                round(liquidatable_pnl, 10)
                if liquidatable_pnl is not None
                else None
            ),
            mid_equity_usd=round(mid_equity, 10),
            liquidatable_equity_usd=(
                round(liquidatable_equity, 10)
                if liquidatable_equity is not None
                else None
            ),
            turnover_usd=round(float(turnover_usd), 10),
            avg_margin_locked_usd=round(average_margin, 10),
            peak_margin_locked_usd=round(next_peak_margin, 10),
            ROI_starting_equity=_ratio(
                authoritative_pnl,
                self.starting_equity_usd,
            ),
            ROI_avg_margin_locked=_ratio(
                authoritative_pnl,
                average_margin,
            ),
            ROI_peak_margin_locked=_ratio(
                authoritative_pnl,
                next_peak_margin,
            ),
            return_on_gross_exposure=_ratio(
                authoritative_pnl,
                gross,
            ),
            roi_status=(
                "LIQUIDATABLE_EXECUTABLE"
                if authoritative_pnl is not None
                else "UNMEASURABLE_NO_EXECUTABLE_EXIT"
            ),
        )
        for name in (
            "starting_equity_usd",
            "free_cash_usd",
            "margin_locked_usd",
            "gross_exposure_usd",
            "net_directional_exposure_usd",
            "realized_pnl_usd",
            "unrealized_mid_pnl_usd",
            "mid_equity_usd",
            "turnover_usd",
            "avg_margin_locked_usd",
            "peak_margin_locked_usd",
        ):
            if not _finite(getattr(snapshot, name)):
                raise ValueError(f"{name} snapshot must be finite")
        for name in (
            "leverage_effective",
            "liquidation_buffer_bps",
            "liquidatable_pnl_usd",
            "liquidatable_equity_usd",
            "ROI_starting_equity",
            "ROI_avg_margin_locked",
            "ROI_peak_margin_locked",
            "return_on_gross_exposure",
        ):
            value = getattr(snapshot, name)
            if value is not None and not _finite(value):
                raise ValueError(f"{name} snapshot must be finite or None")
        if any(not _finite(value) for value in snapshot.leg_notional_usd):
            raise ValueError("leg_notional_usd snapshot must be finite")
        self._margin_sum = next_margin_sum
        self._margin_observations = next_margin_observations
        self._last_observed_margin = next_last_observed_margin
        self._peak_margin = next_peak_margin
        self._latest = snapshot
        return snapshot


def _ratio(numerator: float | None, denominator: float) -> float | None:
    if numerator is None or denominator <= 0:
        return None
    ratio = numerator / denominator
    return round(ratio, 10) if math.isfinite(ratio) else None


def _finite(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed)


def _finite_positive(value: object) -> bool:
    return _finite(value) and float(value) > 0


def equity_after_fill_fee_receipt(*, starting_equity_usd: object, realized_pnl_usd: object, fee_usd: object) -> dict[str, object]:
    """Reconcile paper equity after each observed fill and its fee."""

    try:
        starting, pnl, fee = float(starting_equity_usd), float(realized_pnl_usd), float(fee_usd)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "ACCOUNTING_INPUT_INVALID"}
    if not all(_finite(value) for value in (starting, pnl, fee)) or starting < 0.0 or fee < 0.0:
        return {"status": "UNMEASURABLE", "reason": "ACCOUNTING_INPUT_INVALID"}
    equity = starting + pnl - fee
    return {"status": "PROVEN", "equity_usd": round(equity, 10), "real_execution": False}


def _capital_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _capital_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _capital_finite(value: Any) -> bool:
    return _finite(value)


def _capital_number(value: Any) -> float | None:
    return float(value) if _capital_finite(value) else None


def capital_accounting_safety_receipt(snapshot: CapitalAccountingSnapshot) -> dict[str, Any]:
    valid = isinstance(snapshot, CapitalAccountingSnapshot) and all(_finite(getattr(snapshot, field)) for field in ("starting_equity_usd", "free_cash_usd", "margin_locked_usd", "gross_exposure_usd", "mid_equity_usd"))
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_ACCOUNTING_SAFE" if valid else "CAPITAL_ACCOUNTING_UNSAFE", fail_closed=not valid)


def capital_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_FIELD_PRESENT" if valid else "CAPITAL_FIELD_MISSING", field=field, fail_closed=not valid)


def capital_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_FIELD_NON_NULL" if valid else "CAPITAL_FIELD_NULL", field=field, fail_closed=not valid)


def capital_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_FIELD_TYPE_VALID" if valid else "CAPITAL_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def capital_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _capital_finite(value)
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_VALUE_FINITE" if valid else "CAPITAL_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def capital_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _capital_integer(event_ts_ms) and _capital_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_EVENT_WITHIN_CUTOFF" if valid else "CAPITAL_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def capital_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _capital_integer(event_ts_ms) and _capital_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_EVENT_AGE_VALID" if valid else "CAPITAL_EVENT_TOO_OLD", fail_closed=not valid)


def capital_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_EVENTS_UNIQUE" if valid else "CAPITAL_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def capital_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _capital_integer(attempts) and _capital_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_RETRY_BOUNDED" if valid else "CAPITAL_RETRY_UNSAFE", fail_closed=not valid)


def capital_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_REPLAY_DETERMINISTIC" if valid else "CAPITAL_REPLAY_DIVERGED", fail_closed=not valid)


def capital_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_FILLS_UNIQUE" if valid else "CAPITAL_FILL_DUPLICATED", fail_closed=not valid)


def capital_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_REJECTION_NO_DEBIT" if valid else "CAPITAL_REJECTION_DEBITED", fail_closed=not valid)


def capital_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close, open_size, fee = _capital_number(close_quantity), _capital_number(open_quantity), _capital_number(fee_amount)
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_PARTIAL_CLOSE_COSTED" if valid else "CAPITAL_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def capital_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close, open_size, release = _capital_number(close_quantity), _capital_number(open_quantity), _capital_number(released_margin)
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_TOTAL_CLOSE_RELEASED" if valid else "CAPITAL_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def capital_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark, best_bid, best_ask = _capital_number(mark_price), _capital_number(bid), _capital_number(ask)
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_MARK_LIQUIDABLE" if valid else "CAPITAL_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def capital_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = _capital_number(balance)
    valid = value is not None and value >= 0
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_BALANCE_NON_NEGATIVE" if valid else "CAPITAL_BALANCE_NEGATIVE", fail_closed=not valid)


def capital_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value, normalized = _capital_number(amount), str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_FUNDING_SIGN_VALID" if valid else "CAPITAL_FUNDING_SIGN_INVALID", fail_closed=not valid)


def capital_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount, rate = _capital_number(fee_amount), _capital_number(token_to_pnl_rate)
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_CONVERSION_PROVEN" if valid else "CAPITAL_CONVERSION_MISSING", fail_closed=not valid)


def capital_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_COMMIT_ATOMIC" if valid else "CAPITAL_COMMIT_PARTIAL", fail_closed=not valid)


def capital_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _capital_base("PROVEN" if valid else "REJECTED", verdict="CAPITAL_WRITES_UNIQUE" if valid else "CAPITAL_DOUBLE_WRITE", fail_closed=not valid)


def capital_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only") is True
        and check.get("real_execution") is False
        and check.get("fail_closed") is False
        and bool(str(check.get("verdict") or "").strip())
        for check in checks
    )
    return _capital_base(
        "PROVEN" if valid else "REJECTED",
        verdict="CAPITAL_DONE_COVERED" if valid else "CAPITAL_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


__all__ = [
    "CapitalAccountingSnapshot",
    "CapitalAccountingTracker",
    "PositionCapitalInput",
    "equity_after_fill_fee_receipt",
    "capital_accounting_safety_receipt",
    "capital_required_field_receipt",
    "capital_null_field_receipt",
    "capital_field_type_receipt",
    "capital_finite_receipt",
    "capital_cutoff_receipt",
    "capital_age_receipt",
    "capital_duplicate_receipt",
    "capital_retry_receipt",
    "capital_replay_receipt",
    "capital_fill_duplicate_receipt",
    "capital_rejection_no_debit_receipt",
    "capital_partial_close_receipt",
    "capital_total_close_release_receipt",
    "capital_mark_liquidability_receipt",
    "capital_balance_receipt",
    "capital_funding_sign_receipt",
    "capital_conversion_receipt",
    "capital_commit_receipt",
    "capital_concurrent_write_receipt",
    "capital_done_receipt",
]
