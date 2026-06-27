from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_models import (
    CopySizingInput,
    CopySizingResult,
    DeltaAction,
    NoTradeReason,
)


ENTRY_ACTIONS = {DeltaAction.OPEN_LONG, DeltaAction.OPEN_SHORT, DeltaAction.ADD, DeltaAction.INCREASE}


def calculate_paper_copy_sizing(inputs: CopySizingInput) -> CopySizingResult:
    """Calculate local paper mock USDC notional from leader/follower equity ratio.

    This mirrors the public copy-trading pattern conservatively: leader position
    notional is scaled by follower equity / leader equity, then capped locally.
    It never creates an order and refuses if critical sizing data is missing.
    """

    reasons: list[str] = []
    warnings: list[str] = []
    coin = inputs.coin.upper()
    if coin in {item.upper() for item in inputs.blocked_assets}:
        reasons.append(NoTradeReason.BLOCKED_ASSET.value)
    if inputs.action_type not in ENTRY_ACTIONS:
        reasons.append(NoTradeReason.REDUCE_OR_CLOSE_NOT_ENTRY.value)
    if inputs.leader_account_value is None or inputs.leader_account_value <= 0:
        reasons.append(NoTradeReason.LEADER_EQUITY_MISSING.value)
    if inputs.follower_equity <= 0 or inputs.max_notional <= 0 or inputs.min_notional < 0:
        reasons.append(NoTradeReason.PAPER_SIZING_INVALID.value)
    leader_position_notional = _leader_position_notional(
        inputs.leader_position_size,
        inputs.leader_reference_price,
    )
    if leader_position_notional is None:
        reasons.append(NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE.value)
    if reasons:
        return CopySizingResult(False, None, None, leader_position_notional, _dedupe(reasons), warnings)

    copy_ratio = (inputs.follower_equity / float(inputs.leader_account_value)) * inputs.leverage_adjustment
    requested = float(leader_position_notional) * max(0.0, copy_ratio)
    if requested < inputs.min_notional:
        return CopySizingResult(
            False,
            requested,
            copy_ratio,
            leader_position_notional,
            [NoTradeReason.COPY_NOTIONAL_TOO_SMALL.value],
            warnings,
        )
    if requested > inputs.max_notional:
        warnings.append(NoTradeReason.COPY_NOTIONAL_CAPPED.value)
        requested = inputs.max_notional
    return CopySizingResult(True, requested, copy_ratio, leader_position_notional, [], warnings)


def _leader_position_notional(size: float | None, price: float | None) -> float | None:
    if size is None or price is None:
        return None
    try:
        size_f = abs(float(size))
        price_f = float(price)
    except (TypeError, ValueError):
        return None
    if size_f <= 0 or price_f <= 0:
        return None
    return size_f * price_f


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
