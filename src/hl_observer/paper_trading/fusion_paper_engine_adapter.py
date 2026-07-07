"""Adapter from fusion copy decisions to the existing PaperEngine."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import os

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote, resolve_copy_conflict
from hl_observer.paper_trading.paper_engine import PaperDecisionResult, PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity
from hl_observer.signals.leader_delta import LeaderDelta


@dataclass(frozen=True, slots=True)
class FusionPaperEngineSummary:
    decisions: tuple[PaperDecisionResult, ...]
    accepted_count: int
    equity_usdt: float
    drawdown_usdt: float
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_count": self.accepted_count,
            "equity_usdt": self.equity_usdt,
            "drawdown_usdt": self.drawdown_usdt,
            "decisions": [
                {
                    "accepted": item.accepted,
                    "trade": asdict(item.trade) if item.trade else None,
                    "position": asdict(item.position) if item.position else None,
                    "equity_usdt": item.equity_usdt,
                    "drawdown_usdt": item.drawdown_usdt,
                    "reason_codes": list(item.reason_codes),
                    "evidence_hash": item.evidence_hash,
                }
                for item in self.decisions
            ],
            "paper_only": self.paper_only,
            "real_execution": self.real_execution,
        }


def run_copy_votes_through_paper_engine(
    votes: tuple[LeaderVote, ...],
    *,
    market_price: float,
    observed_at_ms: int,
    starting_cash_usdt: float = 1000.0,
) -> FusionPaperEngineSummary:
    max_position_usdt = _env_float("HYPERSMART_MAX_POSITION_USDT", 40.0)
    max_total_exposure_usdt = _env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 400.0)
    max_open_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    leverage = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 1.0)
    engine = PaperEngine(
        config=PaperEngineConfig(
            starting_cash_usdt=float(starting_cash_usdt),
            max_position_usdt=max_position_usdt,
            max_total_exposure_usdt=max_total_exposure_usdt,
            max_open_positions=max_open_positions,
            leverage=leverage,
            default_top_depth_usdt=_env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50_000.0),
        )
    )
    conflict = resolve_copy_conflict(votes)
    decisions: list[PaperDecisionResult] = []
    distinct_wallets = len({vote.wallet for vote in votes if vote.wallet})
    latest_vote_ms = max((int(vote.observed_at_ms) for vote in votes if int(vote.observed_at_ms or 0) > 0), default=int(observed_at_ms))
    max_signal_age_ms = _env_int("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", 15_000)
    signal_age_ms = max(0, int(observed_at_ms) - int(latest_vote_ms))
    min_consensus_wallets = _env_int("HYPERSMART_FUSION_COPY_MIN_WALLETS", 2)
    if conflict.decision == "FOLLOW" and conflict.winning_side in {"LONG", "SHORT"}:
        if distinct_wallets < min_consensus_wallets or signal_age_ms > max_signal_age_ms:
            equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
            return FusionPaperEngineSummary(
                decisions=(),
                accepted_count=0,
                equity_usdt=equity,
                drawdown_usdt=drawdown,
            )
        edge_remaining_bps = _consensus_edge_remaining_bps(conflict, distinct_wallets=distinct_wallets)
        delta = LeaderDelta(
            delta_id=f"fusion-paper-engine:{conflict.coin}:{conflict.winning_side}:{observed_at_ms}",
            wallet=votes[0].wallet if votes else "unknown",
            coin=conflict.coin,
            action=LifecycleAction.OPEN_LONG if conflict.winning_side == "LONG" else LifecycleAction.OPEN_SHORT,
            previous_size=0.0,
            current_size=1.0 if conflict.winning_side == "LONG" else -1.0,
            delta_size=1.0 if conflict.winning_side == "LONG" else -1.0,
            observed_at_ms=int(observed_at_ms),
            leader_event_time_ms=int(latest_vote_ms),
            source="fusion_paper_engine_adapter",
            confidence=0.9,
            reason_codes=(),
            evidence_ref="fusion_runtime_consensus",
        )
        decisions.append(
            engine.apply_delta(
                delta,
                market_price=float(market_price),
                observed_at_ms=int(observed_at_ms),
                edge_remaining_bps=edge_remaining_bps,
                spread_bps=_env_float("HYPERSMART_FUSION_COPY_SPREAD_BPS", 6.0),
                estimated_slippage_bps=_env_float("HYPERSMART_FUSION_COPY_SLIPPAGE_BPS", 6.0),
                top_depth_usdt=_env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50_000.0),
                wallet_score=_consensus_wallet_score(conflict, distinct_wallets=distinct_wallets),
                signal_score=_consensus_signal_score(conflict, distinct_wallets=distinct_wallets),
                marks={conflict.coin: float(market_price)},
            )
        )
    equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
    return FusionPaperEngineSummary(
        decisions=tuple(decisions),
        accepted_count=sum(1 for item in decisions if item.accepted),
        equity_usdt=equity,
        drawdown_usdt=drawdown,
    )


def run_distilled_opportunities_through_paper_engine(
    opportunities: tuple[DistilledOpportunity, ...],
    *,
    market_prices: dict[str, float],
    observed_at_ms: int,
    starting_cash_usdt: float = 1000.0,
) -> FusionPaperEngineSummary:
    """Evaluate distilled GitHub-inspired opportunities through PaperEngine.

    This is the safe replacement for direct GitHub-profile materialization. The
    upstream detector already requires fresh multi-wallet consensus, measured
    edge, measured liquidity and measured copy-degradation. This adapter still
    rechecks through RiskEngine/PaperEngine before any local paper position can
    appear in the UI.
    """

    max_position_usdt = _env_float("HYPERSMART_MAX_POSITION_USDT", 40.0)
    max_total_exposure_usdt = _env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 400.0)
    max_open_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    leverage = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 1.0)
    max_entries = max(1, min(_env_int("HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES", 1), 5))
    engine = PaperEngine(
        config=PaperEngineConfig(
            starting_cash_usdt=float(starting_cash_usdt),
            max_position_usdt=max_position_usdt,
            max_total_exposure_usdt=max_total_exposure_usdt,
            max_open_positions=max_open_positions,
            leverage=leverage,
            default_top_depth_usdt=_env_float("HYPERSMART_DISTILLED_TOP_DEPTH_USDT", 75_000.0),
        )
    )
    whale_sizing_enabled = str(_env_str("HYPERSMART_WHALE_CONSENSUS_SIZING", "0")).strip().lower() in {"1", "true", "yes", "on"}
    decisions: list[PaperDecisionResult] = []
    for opportunity in opportunities[:max_entries]:
        coin = str(opportunity.coin or "").upper()
        side = str(opportunity.side or "").upper()
        market_price = float(market_prices.get(coin, 0.0) or 0.0)
        action = LifecycleAction.OPEN_LONG if side == "LONG" else LifecycleAction.OPEN_SHORT
        wallets = ",".join(opportunity.wallets[:5]) or "distilled_cluster"
        margin_scale = 1.0
        sizing_evidence = ""
        if whale_sizing_enabled:
            # Import paresseux: copying/__init__ importe des modules qui dépendent
            # de paper_trading (cycle). Le module de sizing lui-même est pur.
            from hl_observer.copying.whale_consensus_sizing import compute_whale_consensus_sizing

            sizing = compute_whale_consensus_sizing(
                wallet_count=int(opportunity.wallet_count),
                max_signal_age_ms=int(opportunity.max_signal_age_ms),
                total_notional_usdc=float(opportunity.total_notional_usdc),
            )
            margin_scale = sizing.multiplier
            sizing_evidence = f"|whale_sizing:{sizing.tier}:{sizing.multiplier}:" + ",".join(sizing.reasons)
        delta = LeaderDelta(
            delta_id=f"distilled-paper-engine:{coin}:{side}:{observed_at_ms}:{opportunity.wallet_count}",
            wallet=wallets,
            coin=coin,
            action=action,
            previous_size=0.0,
            current_size=1.0 if side == "LONG" else -1.0,
            delta_size=1.0 if side == "LONG" else -1.0,
            observed_at_ms=int(observed_at_ms),
            leader_event_time_ms=max(0, int(observed_at_ms) - int(opportunity.max_signal_age_ms)),
            source="distilled_github_opportunity_detector",
            confidence=min(1.0, max(0.1, float(opportunity.average_liquidity_score))),
            reason_codes=(),
            evidence_ref="distilled_github_consensus" + sizing_evidence,
        )
        decisions.append(
            engine.apply_delta(
                delta,
                market_price=market_price,
                observed_at_ms=int(observed_at_ms),
                edge_remaining_bps=float(opportunity.average_edge_bps),
                spread_bps=_env_float("HYPERSMART_DISTILLED_SPREAD_BPS", 6.0),
                estimated_slippage_bps=_env_float("HYPERSMART_DISTILLED_SLIPPAGE_BPS", 8.0),
                top_depth_usdt=_env_float("HYPERSMART_DISTILLED_TOP_DEPTH_USDT", 75_000.0),
                wallet_score=_distilled_wallet_score(opportunity),
                signal_score=_distilled_signal_score(opportunity),
                marks=market_prices,
                margin_scale=margin_scale,
            )
        )
    equity, _, drawdown = engine.mark_to_market(market_prices or {"UNKNOWN": 0.0})
    return FusionPaperEngineSummary(
        decisions=tuple(decisions),
        accepted_count=sum(1 for item in decisions if item.accepted),
        equity_usdt=equity,
        drawdown_usdt=drawdown,
    )


def _distilled_wallet_score(opportunity: DistilledOpportunity) -> float:
    return round(min(100.0, 55.0 + min(float(opportunity.wallet_count), 6.0) * 7.0 + float(opportunity.average_liquidity_score) * 12.0), 6)


def _distilled_signal_score(opportunity: DistilledOpportunity) -> float:
    return round(min(100.0, 45.0 + min(float(opportunity.average_edge_bps), 80.0) * 0.45 + min(float(opportunity.wallet_count), 6.0) * 6.0), 6)


def _consensus_edge_remaining_bps(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 1e-9)
    dominance = abs(long_score - short_score) / total
    consensus_bonus = min(float(distinct_wallets), 5.0) * 4.0
    gross_signal = dominance * 45.0 + consensus_bonus
    conservative_cost = _env_float("HYPERSMART_FUSION_COPY_COST_BUFFER_BPS", 18.0)
    return round(gross_signal - conservative_cost, 6)


def _consensus_signal_score(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 1e-9)
    dominance = abs(long_score - short_score) / total
    return round(min(100.0, 30.0 + dominance * 45.0 + min(float(distinct_wallets), 5.0) * 5.0), 6)


def _consensus_wallet_score(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 0.0)
    return round(min(100.0, 65.0 + min(float(distinct_wallets), 5.0) * 8.0 + min(total, 20.0) * 0.75), 6)


def _env_str(name: str, default: str) -> str:
    import os

    value = os.environ.get(name)
    return default if value is None else str(value)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return int(default)


__all__ = [
    "FusionPaperEngineSummary",
    "run_copy_votes_through_paper_engine",
    "run_distilled_opportunities_through_paper_engine",
]
