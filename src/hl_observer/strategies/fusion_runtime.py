"""Integrated paper-only fusion runtime.

This module is the concrete wiring layer for the ported ideas: leader-copy
votes, multi-source price discrepancies, funding spikes, triangular paths,
market-making quotes, drawdown protection and paper execution all meet here.
It does not connect wallets, sign payloads, or submit real orders.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, asdict, field
from typing import Iterable


def _env_flag(nom: str, defaut: bool = False) -> bool:
    """Lecture d'un flag d'environnement, deny-by-default.

    Une valeur absente ou illisible ne DOIT jamais elargir une porte : on retombe sur `defaut`
    (qui vaut False pour tous les flags d'echappement). Cf. la lecon des « planchers FAIL-OPEN ».
    """
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    return str(brut).strip().lower() in {"1", "true", "yes", "on"}

from hl_observer.arbitrage.triangular_graph import TriangularEdge, build_triangular_cycles
from hl_observer.edge.edge_source import edge_brut as _edge_brut_mesure
from hl_observer.freshness.horloges import age_du_signal
from hl_observer.signals.porte_copy_whitelist import signal_copy_autorise
from hl_observer.arbitrage.triangular_opportunity_detector import TriangularOpportunity, detect_triangular_opportunities
from hl_observer.integration.board_admission import compute_admission_floor_for_fusion
from hl_observer.funding.funding_opportunity import funding_rates_bps_for_coins
from hl_observer.arbitrage.ws_price_discrepancy_detector import PriceDiscrepancy, detect_ws_price_discrepancies
from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest, PaperOrderResult
from hl_observer.copy_wallet.copy_conflict_resolver import (
    CopyConflictDecision,
    LeaderVote,
    resolve_copy_conflict,
    resolve_copy_conflicts_by_coin,
)
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
    conflict, conflict_votes = _select_copy_conflict(payload.leader_votes)
    _journaliser_fills_leaders(payload.leader_votes)   # #185-source : la whitelist se nourrit ici
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
    # REVUE 2026-07-12 : `paper_engine` est REASSIGNE plus bas (`paper_engine = distilled_engine`).
    # Si on ne lisait ses refus qu'a la fin, on perdrait ceux du moteur COPY -- justement ceux
    # qu'on veut rendre visibles. On les capture donc a la source.
    _refus_moteur_copy: tuple[str, ...] = ()
    paper_orders: list[PaperOrderResult] = []
    paper_order_strategy_ids: list[str] = []
    delta_neutral: list[DeltaNeutralPosition] = []
    funding_payments: list[FundingPayment] = []
    market_price_for_engine = _latest_mid_for_coin(ordered_events, conflict.coin or "")
    market_prices_by_coin = {event.coin.upper(): float(event.mid) for event in ordered_events}
    conflict_context_ms = max(
        [0]
        + [int(vote.observed_at_ms or 0) for vote in conflict_votes]
        + [
            int(event.event_time_ms)
            for event in ordered_events
            if event.coin.upper() == str(conflict.coin or "").upper()
        ]
    )

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
        _adm_floor = compute_admission_floor_for_fusion(
            funding_signals=funding, triangular=triangular,
            distilled_opportunities=distilled_report.opportunities,
            funding_rates_bps_by_coin=funding_rates_bps_for_coins([getattr(s, "coin", "") for s in funding]),
            now_ms=max((event.event_time_ms for event in ordered_events), default=0),
        )
        paper_engine = run_copy_votes_through_paper_engine(
            conflict_votes,
            market_price=float(market_price_for_engine),
            observed_at_ms=conflict_context_ms,
            starting_cash_usdt=float(payload.current_equity),
            admission_floor_power=_adm_floor,
        )
        # Capture AVANT toute reassignation par le chemin distille (cf. plus bas).
        _refus_moteur_copy = tuple(paper_engine.refusal_reasons)
        # ---------------------------------------------------------------------------------
        # BUG 2026-07-12 -- LE VERROU D'EDGE NE GARDAIT PAS CE CHEMIN.
        #
        # Ce bloc n'interrogeait QUE le consensus (`conflict.decision == "FOLLOW"`). Il emettait
        # donc un ordre paper OPEN meme quand `paper_engine` venait de REFUSER (verrou d'edge
        # empirique : accepted_count == 0, motif EDGE_NOT_EMPIRICAL_NO_TRADE / edge < couts).
        #
        # Deux chemins, deux verdicts opposes, sur le meme signal, au meme instant.
        # Ce qui empechait ces ordres de se materialiser n'etait PAS le verrou, mais un filtre
        # de PREFIXE DE NOM en aval (MATERIALIZABLE_STRATEGY_PREFIXES dans
        # ui/fusion_persistent_adapter) : une propriete de securite tenue par un accident de
        # nommage. Prouve par test : moteur accepted_count=0 ET PaperOrderResult(accepted=True).
        #
        # DOCTRINE (P2-3) : celui qui dit la VERITE doit avoir le POUVOIR. L'edge mesure gagne.
        # L'edge mesure est negatif a TOUS les horizons (cf. runtime/calibration/empirical_edge.json)
        # -> un OPEN non garde est un trade a esperance NEGATIVE, ouvert en connaissance de cause.
        #
        # Flag d'echappement pour un A/B explicite, JAMAIS pour la prod :
        #   HYPERSMART_ALLOW_UNGATED_COPY_FOLLOW=1  (defaut 0 = deny-by-default)
        _copy_follow_gate_off = _env_flag("HYPERSMART_ALLOW_UNGATED_COPY_FOLLOW", False)
        _moteur_a_refuse = paper_engine.accepted_count == 0

        if (
            conflict.decision == "FOLLOW"
            and conflict.winning_side
            and _moteur_a_refuse
            and not _copy_follow_gate_off
        ):
            # Le consensus dit OUI, le verrou d'edge dit NON. Le verrou gagne.
            # Le motif precis vient de paper_engine.refusal_reasons, merge dans no_trade plus bas.
            no_trade.append("COPY_FOLLOW_BLOCKED_BY_EMPIRICAL_EDGE_GATE")
        elif conflict.decision == "FOLLOW" and conflict.winning_side and not _copy_whitelist_ok(
            conflict, conflict_votes, no_trade
        ):
            # #185 (20/07) -- DEUXIEME verrou, EN SERIE derriere le verrou d'edge : meme si
            # celui-ci s'ouvrait, on ne suit QUE des leaders individuellement prouves par la
            # whitelist C12 (markout forward reel, deny-by-default). Le motif precis
            # (ABSENTE / VIDE / PERIMEE / HORS_WHITELIST / SANS_ADRESSE) est deja dans no_trade.
            pass
        elif conflict.decision == "FOLLOW" and conflict.winning_side:
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
                leader_votes=conflict_votes,
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
            leader_votes=conflict_votes,
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
                    # la jambe est NUE : sans ce terme, le ledger enregistrerait un revenu de
                    # funding SANS RISQUE DE MARCHE -- une fiction.
                    "price_pnl_usdc": e.price_pnl_usdc,
                    "price_pnl_unknown": e.price_pnl_unknown,
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

    # ---------------------------------------------------------------------------------
    # BUG 2026-07-12 -- LE REFUS LE PLUS IMPORTANT DU BOT ETAIT INVISIBLE.
    #
    # `no_trade` etait alimente par le consensus (NO_COPY_CONSENSUS), le distille
    # (DISTILLED_PAPER_ENGINE_REJECTED) et le triangulaire -- mais JAMAIS par
    # `paper_engine.refusal_reasons`. Or c'est exactement la qu'atterrit le verrou d'edge
    # empirique (EDGE_NOT_EMPIRICAL_NO_TRADE / edge < couts), c.-a-d. LA raison qui explique
    # 100 % des zero-position depuis le 11/07.
    #
    # Symptome vu au dashboard : « 18 deltas d'entree frais · 0 position · aucun refus
    # enregistre ce tick ». Les signaux mouraient EN SILENCE.
    #
    # Le deny-by-default protege les ORDRES. Il ne doit JAMAIS museler la TRACE.
    # Un refus non journalise est un bug, pas une discipline.
    # On merge les refus des DEUX moteurs : celui du copy (capture avant reassignation) ET
    # celui qui reste en place a la fin (copy s'il n'a pas ete remplace, sinon distille).
    for _motif in (*_refus_moteur_copy, *paper_engine.refusal_reasons):
        if _motif and _motif not in no_trade:
            no_trade.append(_motif)

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
    leader_votes: tuple[LeaderVote, ...],
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
                "leader_wallets_count": _winning_wallet_count(conflict, leader_votes),
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


_FILLS_LEADERS_VUS: set = set()


def _journaliser_fills_leaders(leader_votes) -> None:
    """#185-SOURCE (21/07, Flo : « il faut brancher le copy whitelist ») — le producteur qui
    MANQUAIT : la whitelist a besoin de fills leaders horodatés (adresse/coin/side/ts) pour
    mesurer leur markout forward, et RIEN ne les écrivait (leader_wallet vide sur 50 000
    candidats replay, scanners .out vides). Le moteur les VOIT à chaque cycle : on les
    journalise ici. Les mids (au fill + forward) viennent des MARKS au moment de la
    construction — ce fichier ne porte que des faits bruts. Dédup mémoire, append-only,
    jamais bloquant (une panne d'écriture ne touche pas la décision)."""
    try:
        import json as _json
        from pathlib import Path as _P
        p = _P("runtime") / "data" / "leader_fills_bruts.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        lignes = []
        for v in leader_votes or ():
            w = str(getattr(v, "wallet", "") or "")
            if not w:
                continue
            cle = (w, str(getattr(v, "coin", "") or ""), int(getattr(v, "observed_at_ms", 0) or 0))
            if cle in _FILLS_LEADERS_VUS:
                continue
            if len(_FILLS_LEADERS_VUS) > 60_000:      # borne memoire, jamais un bloat
                _FILLS_LEADERS_VUS.clear()
            _FILLS_LEADERS_VUS.add(cle)
            lignes.append(_json.dumps({"adresse": w, "coin": cle[1].upper(),
                                       "side": str(getattr(v, "side", "") or ""),
                                       "ts_ms": cle[2], "real_execution": False},
                                      ensure_ascii=False))
        if lignes:
            with p.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lignes) + "\n")
    except Exception as exc:  # noqa: BLE001 — comptee, jamais silencieuse, jamais bloquante
        try:
            from hl_observer.ops.pannes_internes import noter_echec as _ne
            _ne("fusion_runtime:_journaliser_fills_leaders", exc)
        except Exception:  # noqa: BLE001 — le compteur lui-meme est best-effort
            from hl_observer.ops.echec_silencieux import noter as _ns
            _ns("strategies/fusion_runtime.py:compteur_fallback")


def _copy_whitelist_ok(conflict, leader_votes, no_trade) -> bool:
    """#185 — porte whitelist C12 sur le chemin d'ouverture copy (2e verrou, EN SERIE).

    Extrait les wallets qui ont VOTE pour le cote gagnant et exige que TOUS soient dans
    `runtime/data/copy_whitelist.json` (markout forward positif prouve, deny-by-default).
    En cas de refus, le motif precis part dans `no_trade` — un refus invisible n'existe pas."""
    winning = str(conflict.winning_side or "").upper()
    adresses = [
        v.wallet
        for v in leader_votes
        if str(v.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket_for_runtime(v.side) == winning
    ]
    ok, motif = signal_copy_autorise(adresses)
    if not ok:
        no_trade.append(motif)
    return ok


def _copy_follow_order_metadata(
    *,
    payload: FusionRuntimeInput,
    conflict: CopyConflictDecision,
    leader_votes: tuple[LeaderVote, ...],
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
        for vote in leader_votes
        if str(vote.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket_for_runtime(vote.side) == winning_side
    )
    opposing_votes = tuple(
        vote
        for vote in leader_votes
        if str(vote.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket_for_runtime(vote.side) in {"LONG", "SHORT"}
        and _side_bucket_for_runtime(vote.side) != winning_side
    )
    # 🔴 #318 / P2-6 -- ICI, LA FRAICHEUR ETAIT FABRIQUEE (corrige le 2026-07-13).
    #
    # AVANT :
    #     context_now_ms = max([0] + [e.event_time_ms ...] + [v.observed_at_ms ...])
    #     signal_age_ms  = max(0, context_now_ms - last_vote_ms)
    #
    # Le « maintenant » etait calcule **A PARTIR DES DONNEES**, y compris du signal qu'on datait.
    #   * si le vote GAGNANT etait le plus recent (cas frequent : un signal frais gagne), alors
    #     `context_now == last_vote` -> **age = 0 par construction**. Une TAUTOLOGIE, pas une
    #     mesure ;
    #   * si le flux de prix CALAIT (c'est arrive DEUX fois : 02:32 et 04:08), le « maintenant »
    #     **GELAIT** avec lui -- et un signal vieux de dix minutes restait eternellement
    #     « frais ». **Le bot entrait.**
    #   * et le `max(0, ...)` transformait toute INCOHERENCE d'horloge en « parfaitement frais ».
    #     *Un `max(0, ...)` sur un temps n'est pas une protection : c'est un tapis sous lequel on
    #     balaie une contradiction.*
    #
    # DESORMAIS : une VRAIE montre (`time.time()`), et un refus explicite si on ne peut pas dater.
    # `age_du_signal` refuse un « maintenant » derive des donnees -- l'invariant est TESTE.
    last_vote_ms = max([0] + [int(vote.observed_at_ms or 0) for vote in winning_votes])
    _horodatages_du_lot = (
        [int(event.event_time_ms) for event in ordered_events]
        + [int(vote.observed_at_ms or 0) for vote in leader_votes]
    )
    context_now_ms = int(time.time() * 1000)          # la montre, pas les donnees
    _age = age_du_signal(
        observe_a_ms=last_vote_ms,
        maintenant_local_ms=context_now_ms,
        horodatages_du_lot=_horodatages_du_lot,
    )
    # DENY-BY-DEFAULT : un age qu'on ne sait pas mesurer n'est PAS « frais ». Il est
    # arbitrairement vieux -> le gate de fraicheur refusera. Jamais un zero rassurant.
    signal_age_ms = int(_age.ms) if _age.connu else 999_999
    consensus_wallets = len({str(vote.wallet).lower() for vote in winning_votes if vote.wallet})
    winning_score = float(conflict.long_score if winning_side == "LONG" else conflict.short_score)
    opposing_score = sum(max(0.0, float(vote.score)) for vote in opposing_votes)
    score_margin = max(0.0, winning_score - opposing_score)
    # 🔴 5e EDGE FABRIQUE, trouve le 13/07 par l'invariant AST de G2.
    #
    # Ici vivait : `min(120.0, score_margin * 8.0 + max(0, consensus_wallets - 1) * 6.0)`.
    # Autrement dit : « chaque point de marge de vote vaut 8 bps, chaque wallet supplementaire en
    # vaut 6, et on plafonne a 120 ». Personne n'a jamais mesure ces trois nombres. Un vote de
    # leaders n'est pas une unite de bps.
    #
    # L'edge vient maintenant de la TABLE MESUREE (Q1), sans repli sur une formule.
    # Non mesure => 0.0 => `edge_remaining_bps` devient negatif apres couts => refus.
    _e_vote = _edge_brut_mesure(
        coin=str(conflict.coin or ""),
        direction=str(winning_side or ""),
        signal_age_ms=float(signal_age_ms),
        leader_score=float(winning_score),
        consensus_wallets=float(consensus_wallets),
        signal_ms=float(last_vote_ms or 0),
        strategie="COPY",
        formule_de_secours=None,
    )
    gross_vote_edge_bps = (
        float(_e_vote.valeur_bps)
        if (_e_vote.utilisable and _e_vote.valeur_bps is not None)
        else 0.0
    )
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


def _select_copy_conflict(
    votes: tuple[LeaderVote, ...],
) -> tuple[CopyConflictDecision, tuple[LeaderVote, ...]]:
    """Choose one real per-coin conflict without cross-market vote leakage."""

    grouped = resolve_copy_conflicts_by_coin(votes)
    if not grouped:
        return resolve_copy_conflict(()), ()

    def rank(item: tuple[CopyConflictDecision, tuple[LeaderVote, ...]]) -> tuple[float, ...]:
        decision, coin_votes = item
        winning_wallets = _winning_wallet_count(decision, coin_votes)
        winning_score = (
            float(decision.long_score)
            if decision.winning_side == "LONG"
            else float(decision.short_score)
            if decision.winning_side == "SHORT"
            else 0.0
        )
        opposing_score = (
            float(decision.short_score)
            if decision.winning_side == "LONG"
            else float(decision.long_score)
            if decision.winning_side == "SHORT"
            else max(float(decision.long_score), float(decision.short_score))
        )
        latest_ms = max((int(vote.observed_at_ms or 0) for vote in coin_votes), default=0)
        return (
            1.0 if decision.decision == "FOLLOW" else 0.0,
            float(winning_wallets),
            winning_score - opposing_score,
            winning_score,
            float(latest_ms),
        )

    return max(grouped, key=rank)


def _winning_wallet_count(
    conflict: CopyConflictDecision,
    votes: Iterable[LeaderVote],
) -> int:
    if conflict.winning_side not in {"LONG", "SHORT"}:
        return 0
    coin = str(conflict.coin or "").upper()
    return len(
        {
            str(vote.wallet).lower()
            for vote in votes
            if vote.wallet
            and str(vote.coin or "").upper() == coin
            and _side_bucket_for_runtime(vote.side) == conflict.winning_side
        }
    )


def _external_profile_priority_snapshot() -> tuple[dict[str, object], ...]:
    """Catalogue des profils externes GitHub -- SHADOW-ONLY (pivot ff7aeec).

    BUG CORRIGE (audit 2026-07-11) : ce snapshot declarait en dur `priority_over_internal: True`
    pour CHAQUE profil externe. C'etait FAUX et contraire a la doctrine ("aucun repo externe ne
    bypasse le RiskEngine, le ledger, ou le no-real-trade"). Le champ partait tel quel dans le
    statut, le dashboard et l'audit -> une affirmation fausse dans les donnees.

    REGRESSION CORRIGEE (meme audit) : la premiere correction renvoyait `()`. C'etait trop brutal.
    Ce catalogue ne sert PAS qu'a ce champ : `run_fusion_strategy_runtime` en derive `external_ids`,
    qui NOMME les ordres paper (`_first_available_profile`). A vide, l'arbitrage / le funding / le
    triangulaire retombaient sur un nom sans prefixe `ext_` -> rejetes par le filtre de
    materialisation de `ui/fusion_persistent_adapter` (MATERIALIZABLE_STRATEGY_PREFIXES) -> l'ordre
    paper disparaissait silencieusement (0 position, 0 evenement au ledger, 0 PnL).

    On garde donc le catalogue (le nommage marche), et on dit la VERITE : `priority_over_internal`
    est FALSE. Observation, jamais priorite. Aucun ordre reel, jamais.
    """
    payload = build_external_github_bridge_payload()
    profiles = payload.get("priority_strategy_catalog")
    if not isinstance(profiles, list):
        profiles = []
    return tuple(
        {
            "strategy_id": str(strategy_id),
            # Doctrine shadow-only : un profil externe n'a JAMAIS priorite sur l'interne.
            "priority_over_internal": False,
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
