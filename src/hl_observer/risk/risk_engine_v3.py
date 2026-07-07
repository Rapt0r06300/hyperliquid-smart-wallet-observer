from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class V19RiskGate:
    code: str
    severity: str
    triggered: bool
    blocks_new_entries: bool
    detail: str
    next_action: str


@dataclass(frozen=True, slots=True)
class V19RiskConfig:
    max_session_loss_usdc: float = 5.0
    max_consecutive_losses: int = 3
    max_fee_drag_ratio: float = 0.35
    max_stale_signal_ratio: float = 0.40
    max_edge_negative_ratio: float = 0.35
    max_orphan_close_ratio: float = 0.10
    min_winrate: float = 0.42
    min_profit_factor: float = 0.90
    require_best_strategy_not_no_trade: bool = False


@dataclass(frozen=True, slots=True)
class V19RiskDecision:
    allow_new_entries: bool
    protection_mode: bool
    gates: tuple[V19RiskGate, ...] = field(default_factory=tuple)

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(gate.code for gate in self.gates if gate.triggered and gate.blocks_new_entries)


@dataclass(frozen=True, slots=True)
class SessionEntryRiskContext:
    """Observed paper-session health used before creating a new PaperIntent.

    This context is read-only evidence from logs/snapshots. It never creates a
    trade; it only lets the paper simulator become stricter when the current
    session is dominated by fees, losses, or losing buckets.
    """

    net_pnl_usdc: float = 0.0
    total_decisions: int = 0
    accepted: int = 0
    negative_events: int = 0
    positive_events: int = 0
    fee_drag_ratio: float = 0.0
    stale_reason_count: int = 0
    edge_negative_count: int = 0
    edge_sentinel_count: int = 0
    orphan_close_count: int = 0
    profit_factor_net: float = 1.0
    consecutive_losses: int = 0
    top_losing_coins: tuple[tuple[str, float], ...] = ()
    top_losing_wallets: tuple[tuple[str, float], ...] = ()
    top_losing_actions: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class EntryCostGuardConfig:
    """Pre-entry paper guard against cost-dominated micro trades."""

    min_notional_usdt: float = 25.0
    fee_drag_ratio_threshold: float = 0.35
    fee_drag_min_notional_usdt: float = 40.0
    fee_drag_min_edge_bps: float = 35.0
    loss_streak_threshold: int = 3
    loss_streak_min_edge_bps: float = 45.0
    losing_bucket_threshold_usdc: float = -0.05
    coin_quarantine_min_edge_bps: float = 50.0
    wallet_quarantine_min_edge_bps: float = 50.0


@dataclass(frozen=True, slots=True)
class EntryCostGuardDecision:
    accepted: bool
    reason_codes: tuple[str, ...]
    required_min_notional_usdt: float
    required_min_edge_bps: float
    observed_notional_usdt: float
    observed_edge_bps: float | None
    evidence: dict[str, float | str | bool | None]

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "required_min_notional_usdt": self.required_min_notional_usdt,
            "required_min_edge_bps": self.required_min_edge_bps,
            "observed_notional_usdt": self.observed_notional_usdt,
            "observed_edge_bps": self.observed_edge_bps,
            "evidence": dict(self.evidence),
            "paper_only": True,
            "real_execution": False,
        }


def evaluate_v19_risk_gates(
    *,
    net_pnl_usdc: float,
    total_decisions: int,
    accepted: int,
    negative_events: int,
    positive_events: int,
    fee_drag_ratio: float,
    stale_reason_count: int,
    edge_negative_count: int,
    edge_sentinel_count: int,
    orphan_close_count: int,
    profit_factor_net: float,
    consecutive_losses: int = 0,
    strategy_protection_recommended: bool = False,
    top_losing_coins: Sequence[tuple[str, float]] = (),
    top_losing_wallets: Sequence[tuple[str, float]] = (),
    config: V19RiskConfig | None = None,
) -> V19RiskDecision:
    """Evaluate paper-only anti-loss gates from observed simulation logs.

    This module never creates an external order. It only decides whether the
    local simulation should accept fresh paper entries or switch to a stricter
    observation/protection mode until the user reviews the evidence.
    """

    cfg = config or V19RiskConfig()
    decisions_denominator = max(1, total_decisions)
    trade_denominator = max(1, positive_events + negative_events)
    stale_ratio = stale_reason_count / decisions_denominator
    edge_bad_ratio = (edge_negative_count + edge_sentinel_count) / decisions_denominator
    orphan_ratio = orphan_close_count / decisions_denominator
    winrate = positive_events / trade_denominator
    gates: list[V19RiskGate] = []
    session_loss_triggered = net_pnl_usdc <= -abs(cfg.max_session_loss_usdc)

    gates.append(
        _gate(
            "SESSION_LOSS_HALT",
            session_loss_triggered,
            "CRITICAL",
            True,
            (
                f"net_pnl_usdc={net_pnl_usdc:.6f} <= -{abs(cfg.max_session_loss_usdc):.6f}"
                if session_loss_triggered
                else f"net_pnl_usdc={net_pnl_usdc:.6f} > -{abs(cfg.max_session_loss_usdc):.6f}"
            ),
            "Pause new paper entries, keep marking open paper positions to market, inspect loss attribution.",
        )
    )
    gates.append(
        _gate(
            "LOSS_STREAK_HALT",
            consecutive_losses >= cfg.max_consecutive_losses and cfg.max_consecutive_losses > 0,
            "HIGH",
            True,
            f"consecutive_losses={consecutive_losses} threshold={cfg.max_consecutive_losses}",
            "Apply cooldown on the losing coin/wallet and reduce size before any future paper entry.",
        )
    )
    gates.append(
        _gate(
            "FEE_DRAG_TOO_HIGH",
            fee_drag_ratio > cfg.max_fee_drag_ratio,
            "HIGH",
            True,
            f"fee_drag_ratio={fee_drag_ratio:.6f} threshold={cfg.max_fee_drag_ratio:.6f}",
            "Raise minimum notional/edge and reject micro trades whose expected edge cannot cover fees.",
        )
    )
    gates.append(
        _gate(
            "STALE_SIGNALS_DOMINATE",
            stale_ratio > cfg.max_stale_signal_ratio,
            "HIGH",
            True,
            f"stale_signal_ratio={stale_ratio:.6f} threshold={cfg.max_stale_signal_ratio:.6f}",
            "Prioritize WebSocket/public flow freshness and reject delayed copy candidates.",
        )
    )
    gates.append(
        _gate(
            "EDGE_MODEL_UNRELIABLE",
            edge_bad_ratio > cfg.max_edge_negative_ratio,
            "HIGH",
            True,
            f"edge_bad_ratio={edge_bad_ratio:.6f} threshold={cfg.max_edge_negative_ratio:.6f}",
            "Keep NO_TRADE until edge-after-cost is measurable and positive on fresh data.",
        )
    )
    gates.append(
        _gate(
            "POSITION_MATCHING_UNSTABLE",
            orphan_ratio > cfg.max_orphan_close_ratio,
            "MEDIUM",
            True,
            f"orphan_close_ratio={orphan_ratio:.6f} threshold={cfg.max_orphan_close_ratio:.6f}",
            "Repair lifecycle matching before allowing reduce/close-driven paper PnL changes.",
        )
    )
    gates.append(
        _gate(
            "WINRATE_TOO_LOW",
            accepted > 0 and winrate < cfg.min_winrate,
            "MEDIUM",
            False,
            f"winrate={winrate:.6f} threshold={cfg.min_winrate:.6f}",
            "Make sizing smaller and require stronger consensus/edge on the next run.",
        )
    )
    gates.append(
        _gate(
            "PROFIT_FACTOR_TOO_LOW",
            accepted > 0 and profit_factor_net < cfg.min_profit_factor,
            "MEDIUM",
            False,
            f"profit_factor_net={profit_factor_net:.6f} threshold={cfg.min_profit_factor:.6f}",
            "Run strategy tournament and quarantine configs that lose on validation/holdout.",
        )
    )
    gates.append(
        _gate(
            "STRATEGY_TOURNAMENT_PROTECTION",
            strategy_protection_recommended and cfg.require_best_strategy_not_no_trade,
            "HIGH",
            True,
            "best robust strategy is no_trade_baseline",
            "Do not enter new paper positions until a strategy beats no-trade on validation without lookahead.",
        )
    )

    if top_losing_coins:
        coin, pnl = top_losing_coins[0]
        gates.append(
            _gate(
                "COIN_LOSS_QUARANTINE",
                pnl < 0,
                "LOW",
                False,
                f"worst_coin={coin} pnl={pnl:.6f}",
                "Put the worst coin on stricter edge/cooldown instead of re-entering mechanically.",
            )
        )
    if top_losing_wallets:
        wallet, pnl = top_losing_wallets[0]
        gates.append(
            _gate(
                "WALLET_LOSS_QUARANTINE",
                pnl < 0,
                "LOW",
                False,
                f"worst_wallet={wallet} pnl={pnl:.6f}",
                "Reduce trust for wallets whose recent paper copy result is negative.",
            )
        )

    blocking = any(gate.triggered and gate.blocks_new_entries for gate in gates)
    return V19RiskDecision(
        allow_new_entries=not blocking,
        protection_mode=blocking,
        gates=tuple(gates),
    )


def evaluate_entry_cost_guard(
    *,
    coin: str,
    wallet: str,
    notional_usdt: float,
    edge_net_bps: float | None,
    context: SessionEntryRiskContext | None = None,
    config: EntryCostGuardConfig | None = None,
) -> EntryCostGuardDecision:
    """Reject paper entries that are likely to be dominated by costs.

    The guard uses current paper-session evidence. It is deliberately separate
    from the post-run audit so a bad fee-drag/loss-streak regime can stop new
    PaperIntent creation before another simulated open pays fees.
    """

    cfg = config or EntryCostGuardConfig()
    ctx = context or SessionEntryRiskContext()
    observed_notional = max(0.0, float(notional_usdt or 0.0))
    required_min_notional = float(cfg.min_notional_usdt)
    required_min_edge = 0.0
    reasons: list[str] = []

    fee_drag_active = float(ctx.fee_drag_ratio or 0.0) > float(cfg.fee_drag_ratio_threshold)
    if fee_drag_active:
        required_min_notional = max(required_min_notional, float(cfg.fee_drag_min_notional_usdt))
        required_min_edge = max(required_min_edge, float(cfg.fee_drag_min_edge_bps))
        reasons.append("FEE_DRAG_GUARD_ACTIVE")

    if int(ctx.consecutive_losses or 0) >= int(cfg.loss_streak_threshold):
        required_min_edge = max(required_min_edge, float(cfg.loss_streak_min_edge_bps))
        reasons.append("LOSS_STREAK_REQUIRES_HIGHER_EDGE")

    normalized_coin = str(coin or "").upper()
    normalized_wallet = str(wallet or "").lower()
    worst_coin_pnl = _bucket_pnl(ctx.top_losing_coins, normalized_coin, upper_keys=True)
    worst_wallet_pnl = _bucket_pnl(ctx.top_losing_wallets, normalized_wallet, upper_keys=False)
    if worst_coin_pnl is not None and worst_coin_pnl <= float(cfg.losing_bucket_threshold_usdc):
        required_min_edge = max(required_min_edge, float(cfg.coin_quarantine_min_edge_bps))
        reasons.append("COIN_SIDE_LOSS_QUARANTINE_REQUIRES_HIGHER_EDGE")
    if worst_wallet_pnl is not None and worst_wallet_pnl <= float(cfg.losing_bucket_threshold_usdc):
        required_min_edge = max(required_min_edge, float(cfg.wallet_quarantine_min_edge_bps))
        reasons.append("WALLET_LOSS_QUARANTINE_REQUIRES_HIGHER_EDGE")

    if observed_notional < required_min_notional:
        reasons.append("NO_MICRO_TRADE_NOTIONAL")
    if edge_net_bps is None:
        reasons.append("EDGE_UNMEASURABLE")
    elif float(edge_net_bps) < required_min_edge:
        reasons.append("ENTRY_EDGE_BELOW_SESSION_REQUIREMENT")

    unique = tuple(dict.fromkeys(reasons))
    blocking = tuple(
        reason
        for reason in unique
        if reason
        in {
            "NO_MICRO_TRADE_NOTIONAL",
            "EDGE_UNMEASURABLE",
            "ENTRY_EDGE_BELOW_SESSION_REQUIREMENT",
        }
    )
    return EntryCostGuardDecision(
        accepted=not blocking,
        reason_codes=unique,
        required_min_notional_usdt=round(required_min_notional, 8),
        required_min_edge_bps=round(required_min_edge, 8),
        observed_notional_usdt=round(observed_notional, 8),
        observed_edge_bps=round(float(edge_net_bps), 8) if edge_net_bps is not None else None,
        evidence={
            "fee_drag_ratio": round(float(ctx.fee_drag_ratio or 0.0), 8),
            "fee_drag_active": fee_drag_active,
            "consecutive_losses": float(ctx.consecutive_losses or 0),
            "worst_coin_pnl_usdc": worst_coin_pnl,
            "worst_wallet_pnl_usdc": worst_wallet_pnl,
            "net_pnl_usdc": round(float(ctx.net_pnl_usdc or 0.0), 8),
        },
    )


def decision_to_dict(decision: V19RiskDecision) -> dict:
    return {
        "allow_new_entries": decision.allow_new_entries,
        "protection_mode": decision.protection_mode,
        "blocking_codes": list(decision.blocking_codes),
        "gates": [
            {
                "code": gate.code,
                "severity": gate.severity,
                "triggered": gate.triggered,
                "blocks_new_entries": gate.blocks_new_entries,
                "detail": gate.detail,
                "next_action": gate.next_action,
            }
            for gate in decision.gates
        ],
        "paper_only": True,
        "real_execution": False,
    }


def format_v19_risk_decision(decision: V19RiskDecision) -> str:
    lines = [
        "v19_risk_engine=paper_only",
        f"allow_new_entries={str(decision.allow_new_entries).lower()}",
        f"protection_mode={str(decision.protection_mode).lower()}",
        "blocking_codes=" + ",".join(decision.blocking_codes),
        "gates:",
    ]
    for gate in decision.gates:
        status = "TRIGGERED" if gate.triggered else "OK"
        lines.append(
            f"- {gate.code}: {status} severity={gate.severity} blocks={str(gate.blocks_new_entries).lower()} :: {gate.detail}"
        )
    lines.append("execution=forbidden")
    lines.append("paper_simulation_only=true")
    return "\n".join(lines)


def quarantine_suggestions_from_breakdowns(
    pnl_by_coin: Mapping[str, float],
    pnl_by_wallet: Mapping[str, float],
    pnl_by_action: Mapping[str, float],
    *,
    limit: int = 5,
) -> dict[str, list[dict[str, float | str]]]:
    return {
        "coins": _negative_rank(pnl_by_coin, limit=limit),
        "wallets": _negative_rank(pnl_by_wallet, limit=limit),
        "actions": _negative_rank(pnl_by_action, limit=limit),
    }


def _gate(code: str, triggered: bool, severity: str, blocks: bool, detail: str, next_action: str) -> V19RiskGate:
    return V19RiskGate(
        code=code,
        severity=severity,
        triggered=bool(triggered),
        blocks_new_entries=bool(blocks),
        detail=detail,
        next_action=next_action,
    )


def _negative_rank(values: Mapping[str, float], *, limit: int) -> list[dict[str, float | str]]:
    rows = sorted(((key, float(value)) for key, value in values.items() if value < 0), key=lambda item: item[1])
    return [{"key": key, "pnl_usdc": round(value, 8)} for key, value in rows[:limit]]


def _bucket_pnl(
    buckets: Sequence[tuple[str, float]],
    key: str,
    *,
    upper_keys: bool,
) -> float | None:
    lookup = str(key or "").upper() if upper_keys else str(key or "").lower()
    for bucket_key, pnl in buckets:
        normalized = str(bucket_key or "").upper() if upper_keys else str(bucket_key or "").lower()
        if normalized == lookup:
            return float(pnl)
    return None
