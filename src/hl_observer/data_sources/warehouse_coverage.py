from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hl_observer.storage.models import (
    FollowDecision,
    FollowSignal,
    MarketSnapshot,
    PaperFollowOrder,
    PositionDeltaModel,
    RawEvent,
    RejectedSignal,
    RiskEvent,
    SourceHealth,
    TopWallet,
    WalletBackfillRun,
    WalletCandidateModel,
    WalletSnapshot,
)


@dataclass(frozen=True, slots=True)
class WarehouseCoverageReport:
    now_ms: int
    fresh_window_ms: int
    wallet_candidates_total: int
    public_trade_candidates: int
    selected_top_wallets: int
    fresh_top_wallets: int
    stale_top_wallets: int
    wallet_snapshots_total: int
    fresh_wallet_snapshots: int
    public_trade_events: int
    fresh_public_trade_events: int
    market_snapshots_total: int
    fresh_market_snapshots: int
    position_deltas_total: int
    fresh_position_deltas: int
    fresh_entry_deltas: int
    follow_signals_total: int
    fresh_follow_signals: int
    accepted_follow_decisions: int
    rejected_follow_decisions: int
    rejected_signals_total: int
    risk_events_total: int
    paper_follow_orders_total: int
    backfill_runs_total: int
    failed_backfill_runs: int
    sources_total: int
    unhealthy_sources: int
    readiness: str
    bottlenecks: tuple[str, ...]
    next_actions: tuple[str, ...]


def build_warehouse_coverage_report(
    session: Session,
    *,
    now_ms: int,
    fresh_window_ms: int = 20_000,
) -> WarehouseCoverageReport:
    cutoff = max(0, int(now_ms) - max(1, int(fresh_window_ms)))
    wallet_candidates_total = _count(session, WalletCandidateModel)
    public_trade_candidates = _count_where(session, WalletCandidateModel, WalletCandidateModel.source_name == "public_trades_ws")
    selected_top_wallets = _count_where(session, TopWallet, TopWallet.status == "selected")
    fresh_candidate_wallets = select(func.lower(WalletCandidateModel.address)).where(
        WalletCandidateModel.last_seen_ms >= cutoff
    )
    fresh_delta_wallets = select(func.lower(PositionDeltaModel.wallet_address)).where(
        PositionDeltaModel.detected_at_ms >= cutoff
    )
    fresh_top_wallets = int(
        session.query(func.count(func.distinct(TopWallet.wallet_address)))
        .filter(TopWallet.status == "selected")
        .filter(
            or_(
                TopWallet.selected_at_ms >= cutoff,
                func.lower(TopWallet.wallet_address).in_(fresh_candidate_wallets),
                func.lower(TopWallet.wallet_address).in_(fresh_delta_wallets),
            )
        )
        .scalar()
        or 0
    )
    stale_top_wallets = max(0, selected_top_wallets - fresh_top_wallets)
    wallet_snapshots_total = _count(session, WalletSnapshot)
    fresh_wallet_snapshots = _count_where(session, WalletSnapshot, WalletSnapshot.local_received_ts >= cutoff)
    public_trade_events = _count_where(session, RawEvent, RawEvent.source == "hyperliquid_ws_public_trades")
    fresh_public_trade_events = _count_where(session, RawEvent, RawEvent.source == "hyperliquid_ws_public_trades", RawEvent.fetched_at_ms >= cutoff)
    market_snapshots_total = _count(session, MarketSnapshot)
    fresh_market_snapshots = _count_where(session, MarketSnapshot, MarketSnapshot.exchange_ts >= cutoff)
    position_deltas_total = _count(session, PositionDeltaModel)
    fresh_position_deltas = _count_where(session, PositionDeltaModel, PositionDeltaModel.detected_at_ms >= cutoff)
    fresh_entry_deltas = _count_where(
        session,
        PositionDeltaModel,
        PositionDeltaModel.detected_at_ms >= cutoff,
        PositionDeltaModel.delta_type.in_(("open_long", "open_short", "increase_long", "increase_short")),
    )
    follow_signals_total = _count(session, FollowSignal)
    fresh_follow_signals = _count_where(session, FollowSignal, FollowSignal.created_at_ms >= cutoff)
    accepted_follow_decisions = _count_where(session, FollowDecision, FollowDecision.allowed.is_(True))
    rejected_follow_decisions = _count_where(session, FollowDecision, FollowDecision.allowed.is_(False))
    rejected_signals_total = _count(session, RejectedSignal)
    risk_events_total = _count(session, RiskEvent)
    paper_follow_orders_total = _count(session, PaperFollowOrder)
    backfill_runs_total = _count(session, WalletBackfillRun)
    failed_backfill_runs = _count_where(session, WalletBackfillRun, WalletBackfillRun.status.in_(("FAILED", "PARTIAL")))
    sources_total = _count(session, SourceHealth)
    unhealthy_sources = _count_where(session, SourceHealth, SourceHealth.is_consistent.is_(False))
    bottlenecks = _bottlenecks(
        wallet_candidates_total=wallet_candidates_total,
        selected_top_wallets=selected_top_wallets,
        fresh_top_wallets=fresh_top_wallets,
        fresh_public_trade_events=fresh_public_trade_events,
        fresh_market_snapshots=fresh_market_snapshots,
        fresh_position_deltas=fresh_position_deltas,
        fresh_entry_deltas=fresh_entry_deltas,
        fresh_follow_signals=fresh_follow_signals,
        accepted_follow_decisions=accepted_follow_decisions,
        paper_follow_orders_total=paper_follow_orders_total,
    )
    readiness = "SIMULATION_INPUT_READY" if not bottlenecks else "SIMULATION_INPUT_INCOMPLETE"
    return WarehouseCoverageReport(
        now_ms=now_ms,
        fresh_window_ms=fresh_window_ms,
        wallet_candidates_total=wallet_candidates_total,
        public_trade_candidates=public_trade_candidates,
        selected_top_wallets=selected_top_wallets,
        fresh_top_wallets=fresh_top_wallets,
        stale_top_wallets=stale_top_wallets,
        wallet_snapshots_total=wallet_snapshots_total,
        fresh_wallet_snapshots=fresh_wallet_snapshots,
        public_trade_events=public_trade_events,
        fresh_public_trade_events=fresh_public_trade_events,
        market_snapshots_total=market_snapshots_total,
        fresh_market_snapshots=fresh_market_snapshots,
        position_deltas_total=position_deltas_total,
        fresh_position_deltas=fresh_position_deltas,
        fresh_entry_deltas=fresh_entry_deltas,
        follow_signals_total=follow_signals_total,
        fresh_follow_signals=fresh_follow_signals,
        accepted_follow_decisions=accepted_follow_decisions,
        rejected_follow_decisions=rejected_follow_decisions,
        rejected_signals_total=rejected_signals_total,
        risk_events_total=risk_events_total,
        paper_follow_orders_total=paper_follow_orders_total,
        backfill_runs_total=backfill_runs_total,
        failed_backfill_runs=failed_backfill_runs,
        sources_total=sources_total,
        unhealthy_sources=unhealthy_sources,
        readiness=readiness,
        bottlenecks=bottlenecks,
        next_actions=_next_actions(bottlenecks),
    )


def format_warehouse_coverage_report(report: WarehouseCoverageReport) -> str:
    lines = [
        "warehouse_coverage=simulation_only",
        f"readiness={report.readiness}",
        f"fresh_window_ms={report.fresh_window_ms}",
        f"wallet_candidates_total={report.wallet_candidates_total}",
        f"public_trade_candidates={report.public_trade_candidates}",
        f"selected_top_wallets={report.selected_top_wallets}",
        f"fresh_top_wallets={report.fresh_top_wallets}",
        f"stale_top_wallets={report.stale_top_wallets}",
        f"wallet_snapshots_total={report.wallet_snapshots_total}",
        f"fresh_wallet_snapshots={report.fresh_wallet_snapshots}",
        f"public_trade_events={report.public_trade_events}",
        f"fresh_public_trade_events={report.fresh_public_trade_events}",
        f"market_snapshots_total={report.market_snapshots_total}",
        f"fresh_market_snapshots={report.fresh_market_snapshots}",
        f"position_deltas_total={report.position_deltas_total}",
        f"fresh_position_deltas={report.fresh_position_deltas}",
        f"fresh_entry_deltas={report.fresh_entry_deltas}",
        f"follow_signals_total={report.follow_signals_total}",
        f"fresh_follow_signals={report.fresh_follow_signals}",
        f"accepted_follow_decisions={report.accepted_follow_decisions}",
        f"rejected_follow_decisions={report.rejected_follow_decisions}",
        f"paper_follow_orders_total={report.paper_follow_orders_total}",
        f"risk_events_total={report.risk_events_total}",
        f"sources_total={report.sources_total}",
        f"unhealthy_sources={report.unhealthy_sources}",
        "bottlenecks:",
    ]
    lines.extend(f"- {item}" for item in report.bottlenecks) if report.bottlenecks else lines.append("- none")
    lines.append("next_actions:")
    lines.extend(f"- {item}" for item in report.next_actions)
    lines.extend(
        [
            "read_only=true",
            "execution=forbidden",
            "real_orders_created=0",
            "profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _count(session: Session, model: Any) -> int:
    return int(session.query(func.count()).select_from(model).scalar() or 0)


def _count_where(session: Session, model: Any, *conditions: Any) -> int:
    query = session.query(func.count()).select_from(model)
    for condition in conditions:
        query = query.filter(condition)
    return int(query.scalar() or 0)


def _bottlenecks(**values: int) -> tuple[str, ...]:
    missing: list[str] = []
    if values["wallet_candidates_total"] <= 0:
        missing.append("NO_WALLET_CANDIDATES")
    if values["selected_top_wallets"] <= 0:
        missing.append("NO_TOP_WALLETS_SELECTED")
    if values["fresh_top_wallets"] <= 0:
        missing.append("NO_FRESH_TOP_WALLETS")
    if values["fresh_public_trade_events"] <= 0:
        missing.append("NO_FRESH_PUBLIC_TRADE_EVENTS")
    if values["fresh_market_snapshots"] <= 0:
        missing.append("NO_FRESH_MARKET_PRICES")
    if values["fresh_position_deltas"] <= 0:
        missing.append("NO_FRESH_POSITION_DELTAS")
    if values["fresh_entry_deltas"] <= 0:
        missing.append("NO_FRESH_ENTRY_DELTAS")
    if values["fresh_follow_signals"] <= 0:
        missing.append("NO_FRESH_FOLLOW_SIGNALS")
    if values["accepted_follow_decisions"] <= 0 and values["paper_follow_orders_total"] <= 0:
        missing.append("NO_ACCEPTED_PAPER_DECISIONS")
    return tuple(missing)


def _next_actions(bottlenecks: tuple[str, ...]) -> tuple[str, ...]:
    actions: list[str] = []
    if "NO_WALLET_CANDIDATES" in bottlenecks or "NO_FRESH_PUBLIC_TRADE_EVENTS" in bottlenecks:
        actions.append("Lancer live-public-scan a chaque cycle pour alimenter le pool local de wallets actifs.")
    if "NO_FRESH_TOP_WALLETS" in bottlenecks:
        actions.append("Promouvoir les wallets publics recents puis rafraichir la shortlist chaude.")
    if "NO_FRESH_MARKET_PRICES" in bottlenecks:
        actions.append("Collecter allMids/publicTrades prices avant tout calcul de PnL papier.")
    if "NO_FRESH_POSITION_DELTAS" in bottlenecks or "NO_FRESH_ENTRY_DELTAS" in bottlenecks:
        actions.append("Faire tourner userFills WS sur les 10 leaders chauds et refuser les anciens deltas.")
    if "NO_FRESH_FOLLOW_SIGNALS" in bottlenecks or "NO_ACCEPTED_PAPER_DECISIONS" in bottlenecks:
        actions.append("Calculer edge_remaining net frais; garder no-trade si couts/fraicheur/liquidite ne passent pas.")
    return tuple(actions or ["Continuer la collecte; les donnees minimales pour la simulation sont presentes."])
