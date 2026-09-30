from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_models import DeltaAction, EdgeInputs, NoTradeReason


def compute_edge_remaining_bps(
    inputs: EdgeInputs,
    *,
    min_required_bps: float = 8.0,
    max_copy_degradation_bps: float = 40.0,
) -> tuple[float | None, float, list[str]]:
    reasons: list[str] = []
    if inputs.leader_expected_edge_bps is None:
        return None, _copy_degradation(inputs), [NoTradeReason.EDGE_UNMEASURABLE.value]
    if inputs.signal_freshness_factor <= 0:
        reasons.append(NoTradeReason.STALE_SIGNAL.value)
    if inputs.leader_consistency_factor <= 0:
        reasons.append(NoTradeReason.LOW_CONSISTENCY.value)
    degradation = _copy_degradation(inputs)
    edge = (
        inputs.leader_expected_edge_bps
        * inputs.leader_consistency_factor
        * inputs.signal_freshness_factor
        - degradation
    )
    if edge < min_required_bps:
        reasons.append(NoTradeReason.EDGE_REMAINING_TOO_LOW.value)
    if degradation > max_copy_degradation_bps:
        reasons.append(NoTradeReason.COPY_DEGRADATION_TOO_HIGH.value)
    return edge, degradation, reasons


def signal_freshness_factor(age_ms: int, *, stale_after_ms: int = 300_000) -> float:
    if age_ms < 0:
        return 0.0
    if stale_after_ms <= 0:
        return 0.0
    return max(0.0, 1.0 - age_ms / stale_after_ms)


def liquidity_penalty_bps(liquidity_score: float, *, min_liquidity_score: float = 0.50) -> float:
    if liquidity_score >= min_liquidity_score:
        return 0.0
    return (min_liquidity_score - max(0.0, liquidity_score)) * 100.0


def price_deviation_penalty_bps(
    action_type: DeltaAction,
    leader_reference_price: float | None,
    current_mid: float | None,
) -> float:
    """Return adverse price movement in bps for a copied entry.

    For long entries, a higher current price is worse. For short entries, a
    lower current price is worse. Ambiguous add/increase direction is left to
    other gates unless position sign is available in a future batch.
    """

    if leader_reference_price in (None, 0) or current_mid in (None, 0):
        return 0.0
    try:
        leader_price = float(leader_reference_price)
        current_price = float(current_mid)
    except (TypeError, ValueError):
        return 0.0
    if leader_price <= 0 or current_price <= 0:
        return 0.0
    if action_type == DeltaAction.OPEN_LONG:
        adverse = max(0.0, current_price - leader_price)
    elif action_type == DeltaAction.OPEN_SHORT:
        adverse = max(0.0, leader_price - current_price)
    else:
        adverse = 0.0
    return adverse / leader_price * 10_000.0


def _copy_degradation(inputs: EdgeInputs) -> float:
    return (
        inputs.delay_cost_bps
        + inputs.spread_bps
        + inputs.slippage_bps
        + inputs.fee_bps
        + inputs.liquidity_penalty_bps
        + inputs.adverse_selection_penalty_bps
        + inputs.crowding_penalty_bps
        + inputs.funding_penalty_bps
    )
