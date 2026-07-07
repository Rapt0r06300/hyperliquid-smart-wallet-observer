from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.evidence.decision_ledger import PaperDecisionEvidence, evidence_from_paper_result
from hl_observer.paper_trading.paper_engine import PaperDecisionResult, PaperEngine, PaperEngineConfig
from hl_observer.signals.leader_delta import LeaderDelta


@dataclass(frozen=True, slots=True)
class PriceTick:
    coin: str
    timestamp_ms: int
    mid_price: float
    source_ref: str = "price_tick"


@dataclass(frozen=True, slots=True)
class BacktestExperimentConfig:
    latency_ms: int = 0
    edge_remaining_bps: float = 80.0
    spread_bps: float = 2.0
    estimated_slippage_bps: float = 2.0
    top_depth_usdt: float = 100_000.0
    wallet_score: float = 90.0
    signal_score: float = 80.0
    paper: PaperEngineConfig = field(default_factory=PaperEngineConfig)


@dataclass(frozen=True, slots=True)
class BacktestReplayDecision:
    delta_id: str
    coin: str
    action: str
    decision_time_ms: int
    fill_tick_time_ms: int | None
    accepted: bool
    stopped_reason: str
    equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    evidence_hash: str | None


@dataclass(frozen=True, slots=True)
class BacktestExperimentResult:
    decisions: tuple[BacktestReplayDecision, ...]
    evidence: tuple[PaperDecisionEvidence, ...]
    final_equity_usdt: float
    realized_pnl_usdt: float
    max_drawdown_usdt: float
    skipped_no_future_price: int
    warning: str = "historical result is not future profit"


def run_paper_replay_experiment(
    *,
    deltas: list[LeaderDelta],
    price_ticks: list[PriceTick],
    config: BacktestExperimentConfig | None = None,
) -> BacktestExperimentResult:
    cfg = config or BacktestExperimentConfig()
    engine = PaperEngine(config=cfg.paper)
    ticks_by_coin: dict[str, list[PriceTick]] = {}
    for tick in sorted(price_ticks, key=lambda item: item.timestamp_ms):
        if tick.mid_price > 0:
            ticks_by_coin.setdefault(tick.coin.upper(), []).append(tick)

    decisions: list[BacktestReplayDecision] = []
    evidences: list[PaperDecisionEvidence] = []
    skipped_no_future_price = 0

    for delta in sorted(deltas, key=lambda item: item.observed_at_ms):
        decision_time = delta.observed_at_ms + max(0, cfg.latency_ms)
        tick = _first_tick_at_or_after(ticks_by_coin.get(delta.coin.upper(), []), decision_time)
        if tick is None:
            skipped_no_future_price += 1
            equity, unrealized, drawdown = engine.mark_to_market(_latest_marks_before(ticks_by_coin, decision_time))
            decisions.append(
                BacktestReplayDecision(
                    delta_id=delta.delta_id,
                    coin=delta.coin,
                    action=delta.action.value,
                    decision_time_ms=decision_time,
                    fill_tick_time_ms=None,
                    accepted=False,
                    stopped_reason="NO_FUTURE_PRICE_TICK",
                    equity_usdt=equity,
                    realized_pnl_usdt=engine.realized_pnl_usdt,
                    unrealized_pnl_usdt=unrealized,
                    evidence_hash=None,
                )
            )
            continue

        result: PaperDecisionResult = engine.apply_delta(
            delta,
            market_price=tick.mid_price,
            observed_at_ms=decision_time,
            edge_remaining_bps=cfg.edge_remaining_bps,
            spread_bps=cfg.spread_bps,
            estimated_slippage_bps=cfg.estimated_slippage_bps,
            top_depth_usdt=cfg.top_depth_usdt,
            wallet_score=cfg.wallet_score,
            signal_score=cfg.signal_score,
            marks={tick.coin.upper(): tick.mid_price},
        )
        evidence = evidence_from_paper_result(
            delta,
            result,
            source_refs=("leader_delta", tick.source_ref, "paper_engine"),
        )
        evidences.append(evidence)
        decisions.append(
            BacktestReplayDecision(
                delta_id=delta.delta_id,
                coin=delta.coin,
                action=delta.action.value,
                decision_time_ms=decision_time,
                fill_tick_time_ms=tick.timestamp_ms,
                accepted=result.accepted,
                stopped_reason="ACCEPTED" if result.accepted else "NO_TRADE",
                equity_usdt=result.equity_usdt,
                realized_pnl_usdt=result.realized_pnl_usdt,
                unrealized_pnl_usdt=result.unrealized_pnl_usdt,
                evidence_hash=evidence.evidence_hash,
            )
        )

    final_marks = _latest_marks_before(ticks_by_coin, 2**63 - 1)
    final_equity, _, max_drawdown = engine.mark_to_market(final_marks)
    return BacktestExperimentResult(
        decisions=tuple(decisions),
        evidence=tuple(evidences),
        final_equity_usdt=final_equity,
        realized_pnl_usdt=round(engine.realized_pnl_usdt, 8),
        max_drawdown_usdt=max_drawdown,
        skipped_no_future_price=skipped_no_future_price,
    )


def _first_tick_at_or_after(ticks: list[PriceTick], timestamp_ms: int) -> PriceTick | None:
    for tick in ticks:
        if tick.timestamp_ms >= timestamp_ms:
            return tick
    return None


def _latest_marks_before(ticks_by_coin: dict[str, list[PriceTick]], timestamp_ms: int) -> dict[str, float]:
    marks: dict[str, float] = {}
    for coin, ticks in ticks_by_coin.items():
        latest = None
        for tick in ticks:
            if tick.timestamp_ms <= timestamp_ms:
                latest = tick
            else:
                break
        if latest is not None:
            marks[coin] = latest.mid_price
    return marks


__all__ = [
    "BacktestExperimentConfig",
    "BacktestExperimentResult",
    "BacktestReplayDecision",
    "PriceTick",
    "run_paper_replay_experiment",
]
