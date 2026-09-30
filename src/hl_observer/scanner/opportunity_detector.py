from __future__ import annotations

from hl_observer.scanner.scanner_models import MissedOpportunity, MissedOpportunityReason, SignalObservation


def detect_missed_opportunity(
    observation: SignalObservation,
    *,
    max_signal_age_ms: int = 60_000,
    min_edge_required_bps: float = 8.0,
    min_liquidity_score: float = 0.20,
    max_copy_degradation_bps: float = 35.0,
) -> MissedOpportunity | None:
    """Return a missed-opportunity/no-trade reason for one observed signal."""

    age_ms = max(0, int(observation.now_ms) - int(observation.observed_at_ms))
    reason: str | None = None
    message: str | None = None
    next_action: str | None = None
    severity = "INFO"
    if age_ms > max_signal_age_ms:
        reason = MissedOpportunityReason.STALE_SIGNAL.value
        message = "The signal arrived too late to simulate without unrealistic fill assumptions."
        next_action = "Improve hot scan freshness or reduce the watched shortlist."
    elif observation.current_mid is None or observation.current_mid <= 0:
        reason = MissedOpportunityReason.MISSING_CURRENT_MID.value
        message = "No current mid price was available, so edge after costs could not be measured."
        next_action = "Ensure allMids or public trade marks are fresh for this coin."
        severity = "WARN"
    elif observation.edge_remaining_bps is None:
        reason = MissedOpportunityReason.EDGE_UNMEASURABLE.value
        message = "The signal has no measurable edge_remaining_bps."
        next_action = "Collect leader history, current mid, spread, slippage, fees and latency inputs."
        severity = "WARN"
    elif observation.edge_remaining_bps < min_edge_required_bps:
        reason = MissedOpportunityReason.EDGE_REMAINING_TOO_LOW.value
        message = "Edge remaining after costs is below the local simulation threshold."
        next_action = "Keep observing; do not simulate until edge remains positive after costs."
    elif observation.liquidity_score < min_liquidity_score:
        reason = MissedOpportunityReason.LIQUIDITY_TOO_LOW.value
        message = "Liquidity score is too low for a realistic local fill."
        next_action = "Require stronger liquidity or smaller notional."
    elif observation.copy_degradation_bps > max_copy_degradation_bps:
        reason = MissedOpportunityReason.COPY_DEGRADATION_TOO_HIGH.value
        message = "Delay, spread, slippage, fees or price movement degraded the opportunity too much."
        next_action = "Prefer fresher events or more liquid coins."
    elif observation.action_type.upper() in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"} and not observation.has_matching_paper_position:
        reason = MissedOpportunityReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value
        message = "Leader close/reduce has no matching local paper position."
        next_action = "Only close local positions that were opened by this session."
    elif observation.open_positions_count >= observation.max_open_positions:
        reason = MissedOpportunityReason.MAX_OPEN_PAPER_TRADES_REACHED.value
        message = "The local paper portfolio is at its max open position limit."
        next_action = "Wait for a simulated position to close or lower exposure elsewhere."

    if reason is None:
        return None
    return MissedOpportunity(
        reason=reason,
        wallet_address=observation.wallet_address,
        coin=observation.coin,
        action_type=observation.action_type,
        observed_at_ms=observation.observed_at_ms,
        detected_at_ms=observation.now_ms,
        component="opportunity_detector",
        message=message or "Signal refused.",
        next_action=next_action or "Continue observation only.",
        severity=severity,
        details={
            "age_ms": age_ms,
            "edge_remaining_bps": observation.edge_remaining_bps,
            "liquidity_score": observation.liquidity_score,
            "copy_degradation_bps": observation.copy_degradation_bps,
            "source": observation.source,
        },
    )

