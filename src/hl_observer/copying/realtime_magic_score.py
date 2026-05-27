from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RealtimeCopyRiskConfig:
    """Pessimistic local scoring config for realtime copy simulation only."""

    min_edge_required_bps: float = 8.0
    max_signal_age_ms: int = 10 * 60_000
    fee_bps: float = 4.0
    spread_bps: float = 3.0
    slippage_bps: float = 5.0
    latency_cost_bps_per_minute: float = 1.5
    max_latency_cost_bps: float = 18.0
    adverse_selection_penalty_bps: float = 3.0
    funding_penalty_bps: float = 0.0
    min_liquidity_score: float = 0.20
    low_liquidity_penalty_bps: float = 4.0
    single_wallet_penalty_bps: float = 6.0
    crowding_penalty_start_wallets: int = 5
    crowding_penalty_bps_per_wallet: float = 2.0
    max_copy_degradation_bps: float = 35.0
    max_price_deviation_bps: float = 30.0
    starting_equity_usdt: float = 1000.0
    max_position_notional_usdt: float = 50.0
    min_position_notional_usdt: float = 5.0
    max_total_exposure_usdt: float = 200.0
    base_risk_fraction: float = 0.03
    max_risk_fraction: float = 0.05


@dataclass(slots=True)
class RealtimeCopyScoreInput:
    action_type: str
    direction: str
    leader_expected_edge_bps: float | None
    leader_consistency_factor: float
    signal_age_ms: int
    consensus_wallets: int
    liquidity_score: float
    leader_score: float
    leader_reference_price: float
    current_mid: float | None
    leader_notional_usdt: float
    current_open_exposure_usdt: float
    current_open_positions: int
    max_open_positions: int


@dataclass(slots=True)
class RealtimeCopyScore:
    decision: str
    refusal_reasons: list[str]
    signal_freshness_score: float
    leader_expected_edge_bps: float | None
    leader_consistency_factor: float
    consensus_wallets: int
    consensus_factor: float
    liquidity_score: float
    leader_score: float
    copy_degradation_bps: float
    edge_remaining_bps: float | None
    opportunity_score: float
    risk_score: float
    price_deviation_bps: float
    adverse_price_move_bps: float
    simulated_notional_usdt: float
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.decision == "ACCEPT_LOCAL_SIMULATION"


def score_realtime_copy_candidate(
    inputs: RealtimeCopyScoreInput,
    *,
    config: RealtimeCopyRiskConfig | None = None,
) -> RealtimeCopyScore:
    """Score one fresh leader delta for local paper-style simulation.

    The output is deliberately a local research decision. It is not an order,
    not a recommendation, and not a promise of future profit.
    """

    cfg = config or RealtimeCopyRiskConfig()
    reasons: list[str] = []
    warnings: list[str] = []
    action_type = inputs.action_type.upper()
    direction = inputs.direction.upper()
    if action_type in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT", "UNKNOWN"}:
        reason = "REDUCE_OR_CLOSE_NOT_ENTRY" if action_type != "UNKNOWN" else "UNKNOWN_DELTA"
        return _rejected_score(inputs, cfg, [reason], warnings)
    if action_type not in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
        return _rejected_score(inputs, cfg, ["UNKNOWN_DELTA"], warnings)
    if direction not in {"LONG", "SHORT"}:
        return _rejected_score(inputs, cfg, ["UNKNOWN_DELTA"], warnings)
    if inputs.leader_reference_price <= 0:
        return _rejected_score(inputs, cfg, ["PRICE_INVALID"], warnings)
    if inputs.leader_expected_edge_bps is None:
        return _rejected_score(inputs, cfg, ["EDGE_UNMEASURABLE"], warnings)
    if inputs.current_open_positions >= inputs.max_open_positions:
        reasons.append("MAX_OPEN_PAPER_TRADES_REACHED")

    freshness = freshness_factor(inputs.signal_age_ms, cfg.max_signal_age_ms)
    if inputs.signal_age_ms > cfg.max_signal_age_ms:
        reasons.append("STALE_SIGNAL")

    current_mid = inputs.current_mid if inputs.current_mid and inputs.current_mid > 0 else inputs.leader_reference_price
    price_deviation_bps = abs(current_mid - inputs.leader_reference_price) / inputs.leader_reference_price * 10_000.0
    adverse_price_move_bps = _adverse_price_move_bps(
        direction=direction,
        leader_price=inputs.leader_reference_price,
        current_mid=current_mid,
    )
    if adverse_price_move_bps > cfg.max_price_deviation_bps:
        reasons.append("PRICE_DEVIATION_TOO_HIGH")

    consensus_factor = 1.0 + min(0.25, max(0, inputs.consensus_wallets - 1) * 0.08)
    crowding_penalty_bps = max(0, inputs.consensus_wallets - cfg.crowding_penalty_start_wallets) * cfg.crowding_penalty_bps_per_wallet
    if crowding_penalty_bps > 0:
        warnings.append("CROWDING_PENALTY_APPLIED")
    liquidity_score = clamp(inputs.liquidity_score, 0.0, 1.0)
    liquidity_penalty_bps = cfg.low_liquidity_penalty_bps if liquidity_score < cfg.min_liquidity_score else 0.0
    if liquidity_penalty_bps > 0:
        reasons.append("LIQUIDITY_TOO_LOW")
    single_wallet_penalty_bps = cfg.single_wallet_penalty_bps if inputs.consensus_wallets < 2 else 0.0
    delay_cost_bps = min(cfg.max_latency_cost_bps, max(0, inputs.signal_age_ms) / 60_000.0 * cfg.latency_cost_bps_per_minute)
    copy_degradation_bps = (
        delay_cost_bps
        + cfg.spread_bps
        + cfg.slippage_bps
        + cfg.fee_bps
        + liquidity_penalty_bps
        + single_wallet_penalty_bps
        + adverse_price_move_bps
        + cfg.adverse_selection_penalty_bps
        + crowding_penalty_bps
        + cfg.funding_penalty_bps
    )
    if cfg.spread_bps > 20:
        reasons.append("SPREAD_TOO_WIDE")
    if cfg.slippage_bps > 25:
        reasons.append("SLIPPAGE_TOO_HIGH")
    if copy_degradation_bps > cfg.max_copy_degradation_bps:
        reasons.append("COPY_DEGRADATION_TOO_HIGH")

    edge_remaining_bps = (
        inputs.leader_expected_edge_bps
        * clamp(inputs.leader_consistency_factor, 0.0, 1.5)
        * freshness
        * consensus_factor
        - copy_degradation_bps
    )
    if edge_remaining_bps < cfg.min_edge_required_bps:
        reasons.append("EDGE_REMAINING_TOO_LOW")
    if edge_remaining_bps <= 0:
        warnings.append("EDGE_NON_POSITIVE_AFTER_COSTS")

    simulated_notional, sizing_warnings = capped_simulated_notional(inputs, cfg, edge_remaining_bps)
    warnings.extend(sizing_warnings)
    if simulated_notional <= 0:
        reasons.append("MAX_EXPOSURE_REACHED")

    risk_score = risk_score_from_costs(
        copy_degradation_bps=copy_degradation_bps,
        price_deviation_bps=adverse_price_move_bps,
        liquidity_score=liquidity_score,
    )
    opportunity_score = clamp(
        30.0
        + (edge_remaining_bps * 1.35)
        + clamp(inputs.leader_score, 0.0, 100.0) * 0.18
        + (inputs.consensus_wallets - 1) * 5.0
        + liquidity_score * 8.0
        - (100.0 - risk_score) * 0.12,
        0.0,
        100.0,
    )

    deduped_reasons = sorted(set(reasons))
    decision = "REJECT_NO_TRADE" if deduped_reasons else "ACCEPT_LOCAL_SIMULATION"
    return RealtimeCopyScore(
        decision=decision,
        refusal_reasons=deduped_reasons,
        signal_freshness_score=round(freshness, 6),
        leader_expected_edge_bps=round(inputs.leader_expected_edge_bps, 6),
        leader_consistency_factor=round(inputs.leader_consistency_factor, 6),
        consensus_wallets=max(0, int(inputs.consensus_wallets)),
        consensus_factor=round(consensus_factor, 6),
        liquidity_score=round(liquidity_score, 6),
        leader_score=round(clamp(inputs.leader_score, 0.0, 100.0), 6),
        copy_degradation_bps=round(copy_degradation_bps, 6),
        edge_remaining_bps=round(edge_remaining_bps, 6),
        opportunity_score=round(opportunity_score, 6),
        risk_score=round(risk_score, 6),
        price_deviation_bps=round(price_deviation_bps, 6),
        adverse_price_move_bps=round(adverse_price_move_bps, 6),
        simulated_notional_usdt=round(simulated_notional, 6),
        warnings=warnings,
    )


def capped_simulated_notional(
    inputs: RealtimeCopyScoreInput,
    cfg: RealtimeCopyRiskConfig,
    edge_remaining_bps: float,
) -> tuple[float, list[str]]:
    warnings: list[str] = []
    edge_fraction_boost = min(0.02, max(0.0, edge_remaining_bps) / 2_000.0)
    consensus_boost = 0.01 if inputs.consensus_wallets >= 2 else 0.0
    risk_fraction = min(cfg.max_risk_fraction, cfg.base_risk_fraction + edge_fraction_boost + consensus_boost)
    target = cfg.starting_equity_usdt * risk_fraction
    leader_cap = inputs.leader_notional_usdt if inputs.leader_notional_usdt > 0 else cfg.max_position_notional_usdt
    notional = min(cfg.max_position_notional_usdt, max(cfg.min_position_notional_usdt, target), leader_cap)
    remaining_exposure = max(0.0, cfg.max_total_exposure_usdt - max(0.0, inputs.current_open_exposure_usdt))
    if remaining_exposure <= 0:
        return 0.0, ["MAX_TOTAL_EXPOSURE_CAP_ACTIVE"]
    if notional > remaining_exposure:
        notional = remaining_exposure
        warnings.append("POSITION_SIZE_CAPPED_BY_TOTAL_EXPOSURE")
    if notional < cfg.min_position_notional_usdt:
        return 0.0, [*warnings, "POSITION_SIZE_BELOW_MINIMUM"]
    if inputs.leader_notional_usdt > cfg.max_position_notional_usdt:
        warnings.append("POSITION_SIZE_CAPPED_VS_LEADER")
    return notional, warnings


def freshness_factor(signal_age_ms: int, max_signal_age_ms: int) -> float:
    if max_signal_age_ms <= 0:
        return 0.0
    return clamp(1.0 - max(0, signal_age_ms) / max_signal_age_ms, 0.0, 1.0)


def risk_score_from_costs(*, copy_degradation_bps: float, price_deviation_bps: float, liquidity_score: float) -> float:
    cost_penalty = min(45.0, max(0.0, copy_degradation_bps) * 1.2)
    deviation_penalty = min(25.0, max(0.0, price_deviation_bps) * 0.6)
    liquidity_penalty = (1.0 - clamp(liquidity_score, 0.0, 1.0)) * 30.0
    return clamp(100.0 - cost_penalty - deviation_penalty - liquidity_penalty, 0.0, 100.0)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _adverse_price_move_bps(*, direction: str, leader_price: float, current_mid: float) -> float:
    if leader_price <= 0 or current_mid <= 0:
        return 0.0
    if direction.upper() == "LONG":
        return max(0.0, (current_mid - leader_price) / leader_price * 10_000.0)
    if direction.upper() == "SHORT":
        return max(0.0, (leader_price - current_mid) / leader_price * 10_000.0)
    return 0.0


def _rejected_score(
    inputs: RealtimeCopyScoreInput,
    cfg: RealtimeCopyRiskConfig,
    reasons: list[str],
    warnings: list[str],
) -> RealtimeCopyScore:
    freshness = freshness_factor(inputs.signal_age_ms, cfg.max_signal_age_ms)
    liquidity_score = clamp(inputs.liquidity_score, 0.0, 1.0)
    current_mid = inputs.current_mid if inputs.current_mid and inputs.current_mid > 0 else inputs.leader_reference_price
    price_deviation_bps = (
        abs(current_mid - inputs.leader_reference_price) / inputs.leader_reference_price * 10_000.0
        if inputs.leader_reference_price > 0 and current_mid > 0
        else 0.0
    )
    adverse_price_move_bps = _adverse_price_move_bps(
        direction=inputs.direction,
        leader_price=inputs.leader_reference_price,
        current_mid=current_mid,
    )
    return RealtimeCopyScore(
        decision="REJECT_NO_TRADE",
        refusal_reasons=sorted(set(reasons)),
        signal_freshness_score=round(freshness, 6),
        leader_expected_edge_bps=inputs.leader_expected_edge_bps,
        leader_consistency_factor=round(inputs.leader_consistency_factor, 6),
        consensus_wallets=max(0, int(inputs.consensus_wallets)),
        consensus_factor=1.0,
        liquidity_score=round(liquidity_score, 6),
        leader_score=round(clamp(inputs.leader_score, 0.0, 100.0), 6),
        copy_degradation_bps=0.0,
        edge_remaining_bps=None,
        opportunity_score=0.0,
        risk_score=0.0,
        price_deviation_bps=round(price_deviation_bps, 6),
        adverse_price_move_bps=round(adverse_price_move_bps, 6),
        simulated_notional_usdt=0.0,
        warnings=warnings,
    )
