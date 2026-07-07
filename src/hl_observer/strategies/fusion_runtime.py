"""Integrated paper-only fusion runtime.

This module is the concrete wiring layer for the ported ideas: leader-copy
votes, multi-source price discrepancies, funding spikes, triangular paths,
market-making quotes, drawdown protection and paper execution all meet here.
It does not connect wallets, sign payloads, or submit real orders.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Iterable

from hl_observer.arbitrage.triangular_graph import TriangularEdge, build_triangular_cycles
from hl_observer.arbitrage.triangular_opportunity_detector import TriangularOpportunity, detect_triangular_opportunities
from hl_observer.arbitrage.ws_price_discrepancy_detector import PriceDiscrepancy, detect_ws_price_discrepancies
from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest, PaperOrderResult
from hl_observer.copy_wallet.copy_conflict_resolver import CopyConflictDecision, LeaderVote, resolve_copy_conflict
from hl_observer.copy_wallet.copy_latency_profiler import LatencyProfile, profile_copy_latency
from hl_observer.copy_wallet.copy_session_controller import CopySessionState, start_copy_session
from hl_observer.funding.funding_rate_scanner import FundingSignal, scan_funding_rates
from hl_observer.funding.funding_arb_paper import (
    evaluate_funding_arb,
    funding_arb_paper_enabled,
    get_open_funding_arb_positions,
    set_open_funding_arb_positions,
)
from hl_observer.market_making.market_making_paper import PaperMakerQuote, build_paper_maker_quote
from hl_observer.paper_trading.delta_neutral_position import DeltaNeutralPosition, build_delta_neutral_position
from hl_observer.paper_trading.funding_payment_tracker import FundingPayment, compute_funding_payment
from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    FusionPaperEngineSummary,
    run_copy_votes_through_paper_engine,
    run_distilled_opportunities_through_paper_engine,
)
from hl_observer.realtime.low_latency_event_queue import LowLatencyEventQueue, QueuedEvent
from hl_observer.realtime.multi_source_price_stream import PriceEvent, merge_price_events
from hl_observer.risk.portfolio_drawdown_kill_switch import DrawdownKillSwitch, evaluate_drawdown_kill_switch
from hl_observer.signals.distilled_opportunity_detector import (
    DistilledOpportunityReport,
    DistilledSignalCandidate,
    detect_distilled_opportunities,
)
from hl_observer.strategies.controller import StrategyController, StrategyDecision
from hl_observer.strategies.external_simulation_bus import (
    ExternalProfileExecution,
    run_external_profile_simulation_bus,
    summarize_external_profile_executions,
)
from hl_observer.strategies.external_github_bridge import build_external_github_bridge_payload


@dataclass(frozen=True, slots=True)
class FusionRuntimeInput:
    session_id: str
    leader_votes: tuple[LeaderVote, ...]
    price_events: tuple[PriceEvent, ...]
    funding_rows: tuple[dict[str, object], ...]
    triangular_edges: tuple[TriangularEdge, ...]
    latencies_ms: tuple[int, ...] = ()
    peak_equity: float = 1000.0
    current_equity: float = 1000.0
    copy_ratio: float = 0.05
    open_positions: tuple[dict[str, object], ...] = ()
    distilled_signal_candidates: tuple[DistilledSignalCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class FusionRuntimeResult:
    session: CopySessionState
    conflict: CopyConflictDecision
    latency: LatencyProfile
    drawdown: DrawdownKillSwitch
    price_discrepancies: tuple[PriceDiscrepancy, ...]
    funding_signals: tuple[FundingSignal, ...]
    triangular_opportunities: tuple[TriangularOpportunity, ...]
    maker_quotes: tuple[PaperMakerQuote, ...]
    delta_neutral_positions: tuple[DeltaNeutralPosition, ...]
    funding_payments: tuple[FundingPayment, ...]
    paper_orders: tuple[PaperOrderResult, ...]
    paper_order_strategy_ids: tuple[str, ...]
    paper_engine: FusionPaperEngineSummary
    distilled_opportunity_report: DistilledOpportunityReport
    no_trade_reasons: tuple[str, ...]
    external_profile_priority: tuple[dict[str, object], ...] = field(default_factory=tuple)
    funding_arb: dict[str, object] = field(default_factory=dict)
    external_profile_executions: tuple[ExternalProfileExecution, ...] = field(default_factory=tuple)
    external_profile_execution_summary: dict[str, object] = field(default_factory=dict)
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "session": asdict(self.session),
            "conflict": asdict(self.conflict),
            "latency": asdict(self.latency),
            "drawdown": asdict(self.drawdown),
            "price_discrepancies": [asdict(item) for item in self.price_discrepancies],
            "funding_signals": [asdict(item) for item in self.funding_signals],
            "triangular_opportunities": [
                {
                    "path": list(item.cycle.path),
                    "gross_edge_bps": item.gross_edge_bps,
                    "cost_bps": item.cost_bps,
                    "net_edge_bps": item.net_edge_bps,
                    "accepted": item.accepted,
                    "reason": item.reason,
                }
                for item in self.triangular_opportunities
            ],
            "maker_quotes": [asdict(item) for item in self.maker_quotes],
            "delta_neutral_positions": [asdict(item) for item in self.delta_neutral_positions],
            "funding_payments": [asdict(item) for item in self.funding_payments],
            "paper_orders": [asdict(item) for item in self.paper_orders],
            "paper_order_strategy_ids": list(self.paper_order_strategy_ids),
            "paper_engine": self.paper_engine.as_dict(),
            "distilled_opportunity_report": {
                "evaluated_candidates": self.distilled_opportunity_report.evaluated_candidates,
                "opportunities": [asdict(item) for item in self.distilled_opportunity_report.opportunities],
                "rejected_reasons": dict(self.distilled_opportunity_report.rejected_reasons),
                "message": self.distilled_opportunity_report.message,
            },
            "no_trade_reasons": list(self.no_trade_reasons),
            "external_profile_priority": [dict(item) for item in self.external_profile_priority],
            "funding_arb": dict(self.funding_arb),
            "external_profile_execution_summary": dict(self.external_profile_execution_summary),
            "external_profile_executions": [item.as_dict() for item in self.external_profile_executions],
            "paper_only": self.paper_only,
            "real_execution": self.real_execution,
        }


def run_fusion_strategy_runtime(payload: FusionRuntimeInput) -> FusionRuntimeResult:
    external_priority = _external_profile_priority_snapshot()
    external_ids = {str(item["strategy_id"]) for item in external_priority if item.get("strategy_id")}
    session = start_copy_session(
        payload.session_id,
        watchlist=tuple(vote.wallet for vote in payload.leader_votes),
        copy_ratio=payload.copy_ratio,
    )
    conflict = resolve_copy_conflict(payload.leader_votes)
    latency = profile_copy_latency(payload.latencies_ms)
    drawdown = evaluate_drawdown_kill_switch(peak_equity=payload.peak_equity, current_equity=payload.current_equity)

    queue = LowLatencyEventQueue(max_size=2_000)
    for event in payload.price_events:
        queue.push(QueuedEvent(event.event_time_ms, f"{event.source}:{event.coin}:{event.event_time_ms}", asdict(event)), now_ms=max(event.event_time_ms for event in payload.price_events) if payload.price_events else None)
    ordered_events = tuple(
        PriceEvent(
            source=str(item.payload["source"]),
            coin=str(item.payload["coin"]),
            bid=float(item.payload["bid"]),
            ask=float(item.payload["ask"]),
            event_time_ms=int(item.payload["event_time_ms"]),
        )
        for item in queue.drain()
    )
    ordered_events = merge_price_events(ordered_events)

    discrepancies = detect_ws_price_discrepancies(ordered_events)
    funding = scan_funding_rates(payload.funding_rows)
    triangular = tuple(detect_triangular_opportunities(build_triangular_cycles(list(payload.triangular_edges))))
    maker_quotes = _maker_quotes_from_prices(ordered_events)
    distilled_report = detect_distilled_opportunities(
        list(payload.distilled_signal_candidates),
        now_ms=max((event.event_time_ms for event in ordered_events), default=0),
    )

    no_trade: list[str] = []
    paper_orders: list[PaperOrderResult] = []
    paper_order_strategy_ids: list[str] = []
    delta_neutral: list[DeltaNeutralPosition] = []
    funding_payments: list[FundingPayment] = []
    market_price_for_engine = next((event.mid for event in ordered_events if event.coin.upper() == (conflict.coin or "").upper()), 100.0)
    market_prices_by_coin = {event.coin.upper(): float(event.mid) for event in ordered_events}

    connector = LocalPaperExecutionConnector()
    controller = StrategyController(connector)
    if drawdown.triggered:
        no_trade.append(drawdown.reason)
        paper_engine = FusionPaperEngineSummary(
            decisions=(),
            accepted_count=0,
            equity_usdt=float(payload.current_equity),
            drawdown_usdt=max(0.0, float(payload.peak_equity) - float(payload.current_equity)),
        )
    else:
        paper_engine = run_copy_votes_through_paper_engine(
            payload.leader_votes,
            market_price=float(market_price_for_engine),
            observed_at_ms=max((event.event_time_ms for event in ordered_events), default=0),
            starting_cash_usdt=float(payload.current_equity),
        )
        if conflict.decision == "FOLLOW" and conflict.winning_side:
            strategy_id = _first_available_profile(
                external_ids,
                (
                    "ext_rezzecup_whale_mirror_primary",
                    "ext_chaininsighter_priority_copy_session",
                    "ext_immutal0_wallet_filter_caps",
                ),
                fallback="copy_conflict_resolved_follow",
            )
            copy_metadata = _copy_follow_order_metadata(
                payload=payload,
                conflict=conflict,
                ordered_events=ordered_events,
                latency=latency,
            )
            paper_orders.append(
                controller.run_once(
                    StrategyDecision(
                        strategy_id,
                        PaperOrderRequest(
                            conflict.coin or "UNKNOWN",
                            conflict.winning_side,
                            25.0,
                            action="OPEN",
                            strategy_id=strategy_id,
                            reference_price=float(market_price_for_engine),
                            metadata={
                                "source": "copy_conflict_resolver",
                                "profile_family": "copy_follow",
                                "paper_only": True,
                                **copy_metadata,
                            },
                        ),
                    )
                )
            )
            paper_order_strategy_ids.append(strategy_id)
        else:
            no_trade.extend(conflict.reasons or ("NO_COPY_CONSENSUS",))
        if payload.distilled_signal_candidates and not distilled_report.opportunities:
            no_trade.append("NO_DISTILLED_OPPORTUNITY_PASSED_GATES")
        if paper_engine.accepted_count == 0 and distilled_report.opportunities:
            distilled_engine = run_distilled_opportunities_through_paper_engine(
                distilled_report.opportunities,
                market_prices=market_prices_by_coin,
                observed_at_ms=max((event.event_time_ms for event in ordered_events), default=0),
                starting_cash_usdt=float(payload.current_equity),
            )
            if distilled_engine.accepted_count > 0:
                paper_engine = distilled_engine
                opportunity = distilled_report.opportunities[0]
                strategy_id = _first_available_profile(
                    external_ids,
                    (
                        "ext_rezzecup_whale_mirror_primary",
                        "ext_chaininsighter_priority_copy_session",
                        "ext_tony_autonomous_sltp_priority",
                    ),
                    fallback="distilled_whale_consensus_paper",
                )
                paper_orders.append(
                    controller.run_once(
                        StrategyDecision(
                            strategy_id,
                            PaperOrderRequest(
                                opportunity.coin,
                                opportunity.side,
                                25.0,
                                action="OPEN",
                                strategy_id=strategy_id,
                                reference_price=float(market_prices_by_coin.get(opportunity.coin.upper(), 0.0)),
                                metadata={
                                    "source": "distilled_github_opportunity_detector",
                                    "profile_family": "distilled_whale_consensus",
                                    "wallet_count": opportunity.wallet_count,
                                    "average_edge_bps": opportunity.average_edge_bps,
                                    "average_liquidity_score": opportunity.average_liquidity_score,
                                    "paper_only": True,
                                },
                            ),
                        )
                    )
                )
                paper_order_strategy_ids.append(strategy_id)
                no_trade = [reason for reason in no_trade if reason not in {"NO_COPY_CONSENSUS", "COPY_CONFLICT_OR_NO_MAJORITY"}]
            else:
                no_trade.append("DISTILLED_PAPER_ENGINE_REJECTED")

        close_order = _build_consensus_close_order(
            payload.open_positions,
            conflict=conflict,
            ordered_events=ordered_events,
            available_ids=external_ids,
        )
        if close_order is not None:
            paper_orders.append(controller.run_once(StrategyDecision(close_order.strategy_id, close_order)))
            paper_order_strategy_ids.append(close_order.strategy_id)

        for discrepancy in discrepancies[:3]:
            strategy_id = _first_available_profile(
                external_ids,
                (
                    "ext_jack_hl_arbitrage_spread",
                    "ext_jack_hl_arbitrage_alt",
                    "ext_arbibot_cross_exchange_spread",
                    "ext_interexchange_arbitrage",
                    "ext_crypto_arbitrage_spread",
                ),
                fallback="ws_price_discrepancy_paper",
            )
            reference_price = _latest_mid_for_coin(ordered_events, discrepancy.coin)
            paper_orders.append(
                controller.run_once(
                    StrategyDecision(
                        strategy_id,
                        PaperOrderRequest(
                            discrepancy.coin,
                            "LONG",
                            10.0,
                            action="OPEN",
                            order_type="PAPER_ARBITRAGE_SIGNAL",
                            strategy_id=strategy_id,
                            reference_price=reference_price,
                            metadata={
                                "source": "price_discrepancy",
                                "source_a": discrepancy.source_a,
                                "source_b": discrepancy.source_b,
                                "spread_bps": discrepancy.spread_bps,
                                "profile_family": "cross_exchange_arbitrage",
                                "paper_only": True,
                            },
                        ),
                    )
                )
            )
            paper_order_strategy_ids.append(strategy_id)

        for signal in funding:
            if signal.decision == "FUNDING_SPIKE":
                delta_neutral.append(build_delta_neutral_position(coin=signal.coin, long_notional_usdt=50.0, short_notional_usdt=50.0))
                funding_payments.append(compute_funding_payment(coin=signal.coin, side="SHORT", notional_usdt=50.0, funding_rate=0.0001))
                strategy_id = _first_available_profile(
                    external_ids,
                    ("ext_hl_drift_funding_spread", "ext_funding_arb_basis"),
                    fallback="funding_delta_neutral_paper",
                )
                reference_price = _latest_mid_for_coin(ordered_events, signal.coin)
                paper_orders.append(
                    controller.run_once(
                        StrategyDecision(
                            strategy_id,
                            PaperOrderRequest(
                                signal.coin,
                                "HEDGE",
                                50.0,
                                action="OPEN",
                                order_type="PAPER_DELTA_NEUTRAL_FUNDING",
                                strategy_id=strategy_id,
                                reference_price=reference_price,
                                metadata={
                                    "source": "funding_rate_scanner",
                                    "z_score": signal.z_score,
                                    "reason": signal.reason,
                                    "profile_family": "funding_arbitrage",
                                    "paper_only": True,
                                },
                            ),
                        )
                    )
                )
                paper_order_strategy_ids.append(strategy_id)

        for opportunity in triangular[:2]:
            if opportunity.accepted:
                strategy_id = _first_available_profile(
                    external_ids,
                    ("ext_drakkar_triangular_arbitrage", "ext_interexchange_arbitrage", "ext_crypto_arbitrage_spread"),
                    fallback="triangular_paper_detection",
                )
                paper_orders.append(
                    controller.run_once(
                        StrategyDecision(
                            strategy_id,
                            PaperOrderRequest(
                                "/".join(opportunity.cycle.path),
                                "ARBITRAGE",
                                15.0,
                                action="OPEN",
                                order_type="PAPER_TRIANGULAR_ARBITRAGE_SIGNAL",
                                strategy_id=strategy_id,
                                metadata={
                                    "source": "triangular_opportunity_detector",
                                    "path": list(opportunity.cycle.path),
                                    "net_edge_bps": opportunity.net_edge_bps,
                                    "profile_family": "triangular_arbitrage",
                                    "paper_only": True,
                                },
                            ),
                        )
                    )
                )
                paper_order_strategy_ids.append(strategy_id)
            else:
                no_trade.append(opportunity.reason or "TRIANGULAR_NO_TRADE")

    funding_arb_payload: dict[str, object] = {}
    if funding_arb_paper_enabled():
        latest_prices: dict[str, float] = {}
        for event in payload.price_events:
            latest_prices[event.coin.upper()] = float(event.mid)
        now_ms = max((e.event_time_ms for e in payload.price_events), default=0)
        arb_report = evaluate_funding_arb(
            funding_rows=tuple(payload.funding_rows),
            prices=latest_prices,
            positions=get_open_funding_arb_positions(),
            now_ms=int(now_ms),
        )
        set_open_funding_arb_positions(arb_report.positions)
        funding_arb_payload = {
            "enabled": True,
            "open_pairs": arb_report.open_pairs,
            "total_notional_usdt": arb_report.total_notional_usdt,
            "realized_pnl_usdc_step": arb_report.realized_pnl_usdc,
            "events": [
                {
                    "action": e.action,
                    "coin": e.coin,
                    "pair_id": e.pair_id,
                    "reason": e.reason,
                    "rate_bps_per_hour": e.rate_bps_per_hour,
                    "amount_usdc": e.amount_usdc,
                    "net_pnl_usdc": e.net_pnl_usdc,
                    "paper_only": True,
                    "real_execution": False,
                }
                for e in arb_report.events
            ],
            "positions": [
                {
                    "pair_id": p.pair_id,
                    "coin": p.coin,
                    "receiving_side": p.receiving_side,
                    "leg_notional_usdt": p.leg_notional_usdt,
                    "entry_rate_bps_per_hour": p.entry_rate_bps_per_hour,
                    "accrued_funding_usdc": p.accrued_funding_usdc,
                    "opened_at_ms": p.opened_at_ms,
                    "paper_only": True,
                }
                for p in arb_report.positions
            ],
            "message": arb_report.message,
        }

    external_profile_executions = run_external_profile_simulation_bus(
        leader_votes=payload.leader_votes,
        conflict=conflict,
        price_discrepancies=discrepancies,
        funding_signals=funding,
        triangular_opportunities=triangular,
        maker_quotes=maker_quotes,
        paper_orders=tuple(paper_orders),
    )

    return FusionRuntimeResult(
        session=session,
        conflict=conflict,
        latency=latency,
        drawdown=drawdown,
        price_discrepancies=discrepancies,
        funding_signals=funding,
        triangular_opportunities=triangular,
        maker_quotes=maker_quotes,
        delta_neutral_positions=tuple(delta_neutral),
        funding_payments=tuple(funding_payments),
        paper_orders=tuple(paper_orders),
        paper_order_strategy_ids=tuple(paper_order_strategy_ids),
        paper_engine=paper_engine,
        distilled_opportunity_report=distilled_report,
        no_trade_reasons=tuple(no_trade),
        external_profile_priority=external_priority,
        external_profile_executions=external_profile_executions,
        external_profile_execution_summary=summarize_external_profile_executions(external_profile_executions),
        funding_arb=funding_arb_payload,
    )


def _maker_quotes_from_prices(events: Iterable[PriceEvent]) -> tuple[PaperMakerQuote, ...]:
    latest: dict[str, PriceEvent] = {}
    for event in events:
        latest[event.coin.upper()] = event
    return tuple(build_paper_maker_quote(coin=event.coin, mid=event.mid, spread_bps=12.0, size_usdt=20.0) for event in latest.values())


def _latest_mid_for_coin(events: Iterable[PriceEvent], coin: str) -> float:
    latest: PriceEvent | None = None
    coin_upper = str(coin).upper()
    for event in events:
        if event.coin.upper() == coin_upper and (latest is None or event.event_time_ms >= latest.event_time_ms):
            latest = event
    return float(latest.mid) if latest is not None else 0.0


def _build_consensus_close_order(
    open_positions: Iterable[dict[str, object]],
    *,
    conflict: CopyConflictDecision,
    ordered_events: tuple[PriceEvent, ...],
    available_ids: set[str],
) -> PaperOrderRequest | None:
    """Create a local paper close when leader consensus flips against a position."""

    if conflict.decision != "FOLLOW" or not conflict.coin or not conflict.winning_side:
        return None
    coin = str(conflict.coin).upper()
    winning_side = str(conflict.winning_side).upper()
    for position in open_positions:
        pos_coin = str(position.get("coin") or "").upper()
        pos_side = str(position.get("side") or position.get("direction") or "").upper()
        if pos_coin != coin or pos_side not in {"LONG", "SHORT"}:
            continue
        if pos_side == winning_side:
            continue
        notional = _float(position.get("notional_usdt") or position.get("notional"))
        if notional <= 0:
            notional = abs(_float(position.get("size")) * _float(position.get("entry_price") or position.get("avg_price")))
        if notional <= 0:
            notional = 25.0
        strategy_id = _first_available_profile(
            available_ids,
            (
                "ext_rezzecup_whale_mirror_primary",
                "ext_chaininsighter_priority_copy_session",
                "ext_immutal0_wallet_filter_caps",
            ),
            fallback="copy_conflict_resolved_close",
        )
        reference_price = _latest_mid_for_coin(ordered_events, coin)
        return PaperOrderRequest(
            coin,
            pos_side,
            min(notional, 50.0),
            action="CLOSE",
            order_type="PAPER_CLOSE_SIGNAL",
            strategy_id=strategy_id,
            reference_price=reference_price,
            metadata={
                "source": "copy_conflict_resolver",
                "profile_family": "copy_follow",
                "paper_only": True,
                "close_reason": "leader_consensus_flipped_against_open_position",
                "position_key": str(position.get("position_key") or ""),
                "previous_side": pos_side,
                "new_consensus_side": winning_side,
                "leader_wallets_count": 1,
                "signal_age_ms": 0,
                "edge_remaining_bps": 0.0,
                "liquidity_score": 1.0,
                "copy_degradation_bps": 0.0,
            },
        )
    return None


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _copy_follow_order_metadata(
    *,
    payload: FusionRuntimeInput,
    conflict: CopyConflictDecision,
    ordered_events: tuple[PriceEvent, ...],
    latency: LatencyProfile,
) -> dict[str, object]:
    """Attach measurable local evidence to direct copy-profile paper orders.

    External GitHub-derived profiles can propose a paper order, but the live UI
    adapter needs fresh/edge/consensus/liquidity fields before that proposal is
    allowed to touch the 1000 USDT simulation. This metadata is conservative:
    it comes from local leader votes and real read-only Hyperliquid marks.
    """

    winning_side = str(conflict.winning_side or "").upper()
    winning_votes = tuple(
        vote
        for vote in payload.leader_votes
        if str(vote.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket_for_runtime(vote.side) == winning_side
    )
    opposing_votes = tuple(
        vote
        for vote in payload.leader_votes
        if str(vote.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket_for_runtime(vote.side) in {"LONG", "SHORT"}
        and _side_bucket_for_runtime(vote.side) != winning_side
    )
    context_now_ms = max(
        [0]
        + [int(event.event_time_ms) for event in ordered_events]
        + [int(vote.observed_at_ms or 0) for vote in payload.leader_votes]
    )
    last_vote_ms = max([0] + [int(vote.observed_at_ms or 0) for vote in winning_votes])
    signal_age_ms = max(0, context_now_ms - last_vote_ms) if last_vote_ms > 0 else 999_999
    consensus_wallets = len({str(vote.wallet).lower() for vote in winning_votes if vote.wallet})
    winning_score = float(conflict.long_score if winning_side == "LONG" else conflict.short_score)
    opposing_score = sum(max(0.0, float(vote.score)) for vote in opposing_votes)
    score_margin = max(0.0, winning_score - opposing_score)
    gross_vote_edge_bps = min(120.0, score_margin * 8.0 + max(0, consensus_wallets - 1) * 6.0)
    latency_penalty_bps = min(25.0, max(0.0, float(latency.p50_ms or 0)) / 1_000.0 * 2.0)
    freshness_penalty_bps = min(40.0, signal_age_ms / 1_000.0 * 1.5)
    base_cost_bps = 10.0
    copy_degradation_bps = round(base_cost_bps + latency_penalty_bps + freshness_penalty_bps, 6)
    liquidity_score = 0.50 if any(str(event.coin).upper() == str(conflict.coin).upper() for event in ordered_events) else 0.0
    edge_remaining_bps = round(gross_vote_edge_bps - copy_degradation_bps, 6)
    return {
        "leader_wallets_count": consensus_wallets,
        "consensus_wallets": consensus_wallets,
        "winning_vote_score": round(winning_score, 6),
        "opposing_vote_score": round(opposing_score, 6),
        "gross_vote_edge_bps": round(gross_vote_edge_bps, 6),
        "edge_remaining_bps": edge_remaining_bps,
        "net_edge_bps": edge_remaining_bps,
        "signal_age_ms": int(signal_age_ms),
        "liquidity_score": round(liquidity_score, 6),
        "copy_degradation_bps": copy_degradation_bps,
        "latency_p50_ms": int(latency.p50_ms or 0),
        "evidence_source": "leader_votes_plus_hyperliquid_allmids",
    }


def _side_bucket_for_runtime(side: str) -> str:
    raw = str(side or "").upper()
    if "LONG" in raw or "BUY" in raw:
        return "LONG"
    if "SHORT" in raw or "SELL" in raw:
        return "SHORT"
    return "UNKNOWN"


def _external_profile_priority_snapshot() -> tuple[dict[str, object], ...]:
    payload = build_external_github_bridge_payload()
    profiles = payload.get("priority_strategy_catalog")
    if not isinstance(profiles, list):
        profiles = []
    return tuple(
        {
            "strategy_id": str(strategy_id),
            "priority_over_internal": True,
            "paper_only": True,
            "read_only": True,
            "direct_external_execution": False,
        }
        for strategy_id in profiles
    )


def _first_available_profile(
    available_ids: set[str],
    preferred_ids: tuple[str, ...],
    *,
    fallback: str,
) -> str:
    for strategy_id in preferred_ids:
        if strategy_id in available_ids:
            return strategy_id
    return fallback


__all__ = ["FusionRuntimeInput", "FusionRuntimeResult", "run_fusion_strategy_runtime"]
