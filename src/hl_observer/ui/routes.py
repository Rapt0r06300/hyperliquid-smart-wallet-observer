from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from hl_observer import __version__
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.paper.engine import SimulationEngine
from hl_observer.wallets.delta_utils import (
    build_position_consensus,
    copy_delta_action,
    copy_delta_direction,
    delta_event_time_ms,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.storage.models import (
    ApiHealth,
    CollectionRun,
    CoinOpportunity,
    EdgeMetric,
    ExplorerEndpoint,
    ExplorerEvent,
    ExplorerRevalidationResult,
    ExplorerRun,
    ExplorerTransaction,
    ExplorerTransactionTape,
    ExplorerWalletCandidate,
    Fill,
    FollowDecision,
    FollowSignal,
    LeaderboardAddressValidation,
    LeaderboardRow,
    LeaderboardRun,
    LeaderboardWalletCandidate,
    MarketMetric,
    MarketSnapshot,
    MarketUniverseModel,
    OpenOrder,
    PaperFill,
    PaperFollowOrder,
    PaperOrderModel,
    Position,
    PositionDeltaModel,
    RawEvent,
    RejectedSignal,
    RiskEvent,
    SourceHealth,
    FreshnessStatus,
    Signal,
    SignalScoreModel,
    TopWallet,
    TopWalletSource,
    Wallet,
    AutoWatchlist,
    WalletCandidateModel,
    WalletCandidateScoreModel,
    WalletBootstrapRun,
    WalletClosing,
    WalletCoinProfileModel,
    WalletCoinScoreModel,
    WalletDiscoveryRun,
    WalletDiscoverySourceModel,
    WalletMethodologyProfile,
    WalletOpening,
    WalletOpeningPatternStats,
    WalletPlaybook,
    WalletScanQueue,
    WalletScoreModel,
    WalletSource,
)
from hl_observer.ui.action_catalog import build_action_catalog
from hl_observer.ui.event_bus import UiEventBus
from hl_observer.ui.persistent_state import persist_simulation_state, simulation_state_path
from hl_observer.ui.safe_actions import run_safe_action
from hl_observer.ui.schemas import (
    UiActionRequest,
    UiLogLine,
    UiRiskGate,
    UiSignalRow,
    UiStatus,
    UiWalletRow,
)
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def create_router(settings: Settings, state: UiState, bus: UiEventBus) -> APIRouter:
    router = APIRouter()
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    sim_engine = SimulationEngine(settings)
    template_path = Path(__file__).with_name("templates") / "index.html"
    def safe_count(model: type) -> int:
        try:
            with session_factory() as session:
                return int(session.scalar(select(func.count()).select_from(model)) or 0)
        except SQLAlchemyError:
            return 0

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def unique_top_wallets(rows: list[TopWallet], *, limit: int) -> list[TopWallet]:
        unique: list[TopWallet] = []
        seen: set[str] = set()
        for row in rows:
            key = row.wallet_address.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
            if len(unique) >= limit:
                break
        return unique

    def build_heikin_ashi_equity_candles(fills: list[Fill], *, max_points: int = 120) -> list[dict[str, Any]]:
        closed_pnl_rows = [
            row
            for row in sorted(fills, key=lambda item: item.exchange_ts or 0)
            if row.closed_pnl is not None
        ]
        if not closed_pnl_rows:
            return []
        if len(closed_pnl_rows) > max_points:
            closed_pnl_rows = closed_pnl_rows[-max_points:]
        candles: list[dict[str, Any]] = []
        equity = 0.0
        previous_ha_open: float | None = None
        previous_ha_close: float | None = None
        for index, row in enumerate(closed_pnl_rows):
            pnl = float(row.closed_pnl or 0.0)
            open_value = equity
            close_value = equity + pnl
            high_value = max(open_value, close_value)
            low_value = min(open_value, close_value)
            ha_close = (open_value + high_value + low_value + close_value) / 4.0
            ha_open = (open_value + close_value) / 2.0 if previous_ha_open is None else (previous_ha_open + previous_ha_close) / 2.0
            ha_high = max(high_value, ha_open, ha_close)
            ha_low = min(low_value, ha_open, ha_close)
            equity = close_value
            previous_ha_open = ha_open
            previous_ha_close = ha_close
            candles.append(
                {
                    "index": index,
                    "wallet_address": row.wallet_address,
                    "coin": row.coin,
                    "timestamp_ms": row.exchange_ts,
                    "pnl_usdc": round(pnl, 6),
                    "equity_open": round(open_value, 6),
                    "equity_close": round(close_value, 6),
                    "ha_open": round(ha_open, 6),
                    "ha_high": round(ha_high, 6),
                    "ha_low": round(ha_low, 6),
                    "ha_close": round(ha_close, 6),
                    "color": "green" if pnl >= 0 else "red",
                    "source": "local_closed_pnl",
                }
            )
        return candles

    def latest_mid_prices_from_snapshot(raw_snapshot: dict[str, Any] | None) -> dict[str, float]:
        if not isinstance(raw_snapshot, dict):
            return {}
        mids: dict[str, float] = {}
        for coin, value in raw_snapshot.items():
            try:
                mids[str(coin).upper()] = float(value)
            except (TypeError, ValueError):
                continue
        return mids

    def build_bot_equity_candles(events: list[dict[str, Any]], *, max_points: int = 120) -> list[dict[str, Any]]:
        pnl_events = [
            row
            for row in sorted(events, key=lambda item: item.get("observed_at_ms") or 0)
            if row.get("estimated_net_pnl_usdc") is not None
        ]
        if len(pnl_events) > max_points:
            pnl_events = pnl_events[-max_points:]
        candles: list[dict[str, Any]] = []
        equity = 0.0
        previous_ha_open: float | None = None
        previous_ha_close: float | None = None
        for index, row in enumerate(pnl_events):
            pnl = float(row.get("estimated_net_pnl_usdc") or 0.0)
            open_value = equity
            close_value = equity + pnl
            high_value = max(open_value, close_value)
            low_value = min(open_value, close_value)
            ha_close = (open_value + high_value + low_value + close_value) / 4.0
            ha_open = (open_value + close_value) / 2.0 if previous_ha_open is None else (previous_ha_open + previous_ha_close) / 2.0
            ha_high = max(high_value, ha_open, ha_close)
            ha_low = min(low_value, ha_open, ha_close)
            equity = close_value
            previous_ha_open = ha_open
            previous_ha_close = ha_close
            candles.append(
                {
                    "index": index,
                    "wallet_address": row.get("wallet_address"),
                    "coin": row.get("coin"),
                    "timestamp_ms": row.get("observed_at_ms"),
                    "pnl_usdc": round(pnl, 6),
                    "equity_open": round(open_value, 6),
                    "equity_close": round(close_value, 6),
                    "ha_open": round(ha_open, 6),
                    "ha_high": round(ha_high, 6),
                    "ha_low": round(ha_low, 6),
                    "ha_close": round(ha_close, 6),
                    "color": "green" if pnl >= 0 else "red",
                    "source": row.get("bot_replay_action") or "local_reproduction_replay",
                }
            )
        return candles

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(template_path.read_text(encoding="utf-8"))

    @router.get("/api/status", response_model=UiStatus)
    async def status() -> UiStatus:
        audit = run_safety_audit(".")
        counts = {
            "wallets": safe_count(Wallet),
            "raw_events": safe_count(RawEvent),
            "signals": safe_count(Signal),
            "rejected_signals": safe_count(RejectedSignal),
            "paper_orders": safe_count(PaperOrderModel),
            "risk_events": safe_count(RiskEvent),
        }
        last_run: dict[str, Any] | None = None
        try:
            with session_factory() as session:
                run = session.scalar(select(CollectionRun).order_by(desc(CollectionRun.id)).limit(1))
                if run is not None:
                    last_run = {
                        "id": run.id,
                        "mode": run.mode,
                        "success": run.success,
                        "errors_count": run.errors_count,
                        "started_at_ms": run.started_at_ms,
                        "finished_at_ms": run.finished_at_ms,
                    }
        except SQLAlchemyError:
            last_run = None

        gates = [
            UiRiskGate(
                name="mainnet forbidden",
                passed=not settings.execution.enable_mainnet_execution
                and settings.environment != ExecutionEnvironment.MAINNET,
            ),
            UiRiskGate(name="testnet locked", passed=not settings.execution.enable_testnet_execution),
            UiRiskGate(name="paper enabled", passed=settings.environment == ExecutionEnvironment.PAPER),
            UiRiskGate(name="kill switch", passed=not state.kill_switch_active),
            UiRiskGate(name="api stable", passed=True),
            UiRiskGate(name="db status", passed=True if counts is not None else False),
        ]
        safety_status = "STOPPED" if state.kill_switch_active else ("SAFE" if audit.ok else "WARNING")
        return UiStatus(
            app_name="Hyperliquid Smart-Wallet Observer",
            version=__version__,
            mode=settings.environment.value.upper(),
            db_path=settings.database_url,
            mainnet_enabled=settings.execution.enable_mainnet_execution,
            testnet_enabled=settings.execution.enable_testnet_execution,
            paper_enabled=settings.environment == ExecutionEnvironment.PAPER,
            safety_status=safety_status,
            last_collection_run=last_run,
            counts=counts,
            risk_gates=gates,
        )

    @router.get("/api/wallets", response_model=list[UiWalletRow])
    async def wallets() -> list[UiWalletRow]:
        rows: list[UiWalletRow] = []
        with session_factory() as session:
            known_wallets = session.scalars(select(Wallet).order_by(Wallet.created_at.desc()).limit(200)).all()
            for wallet in known_wallets:
                source = session.scalar(
                    select(WalletSource.source)
                    .where(WalletSource.wallet_address == wallet.address)
                    .order_by(WalletSource.created_at.desc())
                    .limit(1)
                )
                score = session.scalar(
                    select(WalletScoreModel.score)
                    .where(WalletScoreModel.wallet_address == wallet.address)
                    .order_by(WalletScoreModel.created_at.desc())
                    .limit(1)
                )
                rows.append(
                    UiWalletRow(
                        address=wallet.address,
                        label=wallet.label,
                        source=source,
                        score=score,
                        status=wallet.status,
                    )
                )
        return rows

    @router.get("/api/positions")
    async def positions(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(Position).order_by(Position.updated_at_ms.desc()).limit(limit)).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "side": row.side,
                "size": row.size,
                "entry_px_estimated": row.entry_px_estimated or row.entry_price,
                "last_px": row.last_px,
                "notional_usdc": row.notional_usdc,
                "source": row.source,
                "confidence_score": row.confidence_score,
                "status": row.status,
                "updated_at_ms": row.updated_at_ms,
            }
            for row in rows
        ]

    @router.get("/api/fills/recent")
    async def recent_fills(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(Fill).order_by(Fill.exchange_ts.desc()).limit(limit)).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "exchange_ts": row.exchange_ts,
                "side": row.side,
                "direction": row.direction,
                "price": row.price,
                "size": row.size,
                "closed_pnl": row.closed_pnl,
                "fee": row.fee,
            }
            for row in rows
        ]

    @router.get("/api/position-deltas/recent")
    async def recent_position_deltas(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(limit)).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "action": row.action,
                "previous_side": row.previous_side,
                "new_side": row.new_side,
                "previous_size": row.previous_size,
                "new_size": row.new_size,
                "delta_size": row.delta_size,
                "delta_notional_usdc": row.delta_notional_usdc,
                "confidence_score": row.confidence_score,
                "detected_at_ms": row.detected_at_ms,
            }
            for row in rows
        ]

    @router.get("/api/open-orders")
    async def open_orders(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(OpenOrder).order_by(OpenOrder.created_at.desc()).limit(limit)).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "oid": row.oid,
                "cloid": row.cloid,
                "raw": row.raw_json,
            }
            for row in rows
        ]

    @router.get("/api/signals", response_model=list[UiSignalRow])
    async def signals() -> list[UiSignalRow]:
        rows: list[UiSignalRow] = []
        with session_factory() as session:
            signals_ = session.scalars(select(Signal).order_by(Signal.created_at.desc()).limit(100)).all()
            for signal in signals_:
                score = session.scalar(
                    select(SignalScoreModel.score)
                    .where(SignalScoreModel.signal_id == signal.id)
                    .order_by(SignalScoreModel.created_at.desc())
                    .limit(1)
                )
                edge = session.scalar(
                    select(EdgeMetric.edge_remaining_bps)
                    .where(EdgeMetric.signal_id == signal.id)
                    .order_by(EdgeMetric.created_at.desc())
                    .limit(1)
                )
                rejected = session.scalar(
                    select(RejectedSignal.reason)
                    .where(RejectedSignal.signal_id == signal.id)
                    .order_by(RejectedSignal.created_at.desc())
                    .limit(1)
                )
                rows.append(
                    UiSignalRow(
                        id=signal.id,
                        wallet=signal.source_wallet,
                        coin=signal.coin,
                        side=signal.side,
                        signal_type=signal.signal_type,
                        signal_score=score,
                        edge_remaining_bps=edge,
                        decision=signal.decision,
                        reject_reason=rejected,
                        created_at=str(signal.created_at),
                    )
                )
        return rows

    @router.get("/api/rejected-signals")
    async def rejected_signals() -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(RejectedSignal).order_by(RejectedSignal.created_at.desc()).limit(100)
            ).all()
            return [
                {
                    "signal_id": row.signal_id,
                    "reason": row.reason,
                    "avoided_loss_bps": None,
                    "missed_gain_bps": None,
                    "timestamp": str(row.created_at),
                }
                for row in rows
            ]

    @router.get("/api/paper")
    async def paper() -> dict[str, Any]:
        with session_factory() as session:
            orders = session.scalars(
                select(PaperOrderModel).order_by(PaperOrderModel.created_at.desc()).limit(100)
            ).all()
            fills = session.scalars(select(PaperFill).order_by(PaperFill.created_at.desc()).limit(100)).all()
        return {
            "paper_orders": [
                {
                    "id": order.id,
                    "signal_id": order.signal_id,
                    "coin": order.coin,
                    "side": order.side,
                    "notional_usdc": order.notional_usdc,
                    "requested_price": order.requested_price,
                    "simulated_fill_price": order.simulated_fill_price,
                    "decision": order.decision,
                }
                for order in orders
            ],
            "paper_fills": [
                {
                    "paper_order_id": fill.paper_order_id,
                    "fill_price": fill.fill_price,
                    "fill_size": fill.fill_size,
                    "fee_bps": fill.fee_bps,
                }
                for fill in fills
            ],
            "estimated_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "open_paper_positions": [],
        }

    @router.get("/api/copy/status")
    async def copy_status() -> dict[str, Any]:
        with session_factory() as session:
            leader_rows = session.scalars(select(TopWallet).order_by(TopWallet.score.desc()).limit(200)).all()
            decisions = session.scalars(select(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(50)).all()
            paper_orders = session.scalars(
                select(PaperFollowOrder).order_by(PaperFollowOrder.created_at_ms.desc()).limit(50)
            ).all()
            deltas_count = int(session.scalar(select(func.count()).select_from(PositionDeltaModel)) or 0)
        leaders = unique_top_wallets(leader_rows, limit=settings.copy_trading.top_leaders)
        return {
            "mode": "PAPER_MOCK_USDC",
            "dry_run_only": True,
            "active_watch": True,
            "target_leaders": settings.copy_trading.top_leaders,
            "polling_interval_seconds": settings.copy_trading.default_interval_seconds,
            "leaders_followed": [
                {
                    "wallet_address": row.wallet_address,
                    "rank": row.rank,
                    "score": row.score,
                    "source": row.source,
                    "status": row.status,
                    "reason": row.notes,
                }
                for row in leaders
            ],
            "leaders_count": len(leaders),
            "position_deltas_observed": deltas_count,
            "follow_decisions": len(decisions),
            "paper_follow_orders": len(paper_orders),
            "no_real_orders": True,
            "no_testnet_executor": True,
            "edge_remaining_bps_required": True,
            "message": "Observation/copy dry-run uniquement. Aucun ordre reel, aucun testnet executor, aucun mainnet.",
        }

    @router.get("/api/copy/leader-activity")
    async def copy_leader_activity(limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with session_factory() as session:
            leaders = session.scalars(select(TopWallet.wallet_address).where(TopWallet.status != "rejected")).all()
            query = select(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(limit)
            if leaders:
                query = (
                    select(PositionDeltaModel)
                    .where(PositionDeltaModel.wallet_address.in_(leaders))
                    .order_by(PositionDeltaModel.detected_at_ms.desc())
                    .limit(limit)
                )
            rows = session.scalars(query).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "action": copy_delta_action(row),
                "raw_action": row.action,
                "delta_type": row.delta_type,
                "previous_size": row.previous_size,
                "new_size": row.new_size,
                "delta_size": row.delta_size,
                "price": row.price,
                "notional_usdc": row.delta_notional_usdc,
                "confidence_score": row.confidence_score,
                "detected_at_ms": row.detected_at_ms,
                "copyable": copy_delta_action(row) in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"},
            }
            for row in rows
        ]

    @router.get("/api/copy/no-trade-report")
    async def copy_no_trade_report(limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(limit, 250))
        reasons: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        with session_factory() as session:
            rejected = session.scalars(select(RejectedSignal).order_by(RejectedSignal.created_at.desc()).limit(limit)).all()
            decisions = session.scalars(select(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)).all()
            deltas = session.scalars(select(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(limit)).all()

        for row in rejected:
            reason = row.reason or row.decision or "rejected_signal"
            reasons[reason] += 1
            samples.append({"source": "rejected_signal", "reason": reason, "signal_id": row.signal_id})
        for row in decisions:
            if row.allowed:
                continue
            row_reasons = row.reasons_json or [row.decision or "follow_decision_rejected"]
            for reason in row_reasons:
                reasons[str(reason)] += 1
                samples.append({"source": "follow_decision", "reason": str(reason), "signal_id": row.signal_id})
        for row in deltas:
            action = copy_delta_action(row)
            if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT", "UNKNOWN"}:
                reason = "leader_reduce_close_not_entry" if action != "UNKNOWN" else "delta_unknown_or_ambiguous"
                reasons[reason] += 1
                samples.append(
                    {
                        "source": "leader_delta",
                        "reason": reason,
                        "wallet_address": row.wallet_address,
                        "coin": row.coin,
                        "action": action,
                    }
                )
        return {
            "mode": "PAPER_MOCK_USDC",
            "dry_run_only": True,
            "edge_remaining_bps_required": True,
            "reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common()],
            "samples": samples[:limit],
            "message": "Chaque refus est conserve comme information de recherche. Aucun refus ne devient un ordre.",
        }

    @router.get("/api/simulation/overview")
    async def simulation_overview(limit: int = 500) -> dict[str, Any]:
        limit = max(1, min(limit, 2_000))
        simulation_started_at_ms = state.simulation_started_at_ms
        current_time_ms = now_ms()
        with session_factory() as session:
            leader_rows = session.scalars(select(TopWallet).order_by(TopWallet.score.desc()).limit(250)).all()
            leaderboard_candidate_rows = session.scalars(
                select(LeaderboardWalletCandidate).order_by(LeaderboardWalletCandidate.leaderboard_score.desc()).limit(500)
            ).all()
            fresh_delta_query = (
                select(PositionDeltaModel)
                .where(
                    or_(
                        PositionDeltaModel.exchange_ts >= simulation_started_at_ms,
                        PositionDeltaModel.detected_at_ms >= simulation_started_at_ms,
                    )
                )
                .order_by(PositionDeltaModel.detected_at_ms.desc())
                .limit(limit)
            )
            deltas = session.scalars(fresh_delta_query).all()
            if not deltas:
                deltas = session.scalars(
                    select(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(min(limit, 250))
                ).all()
            decisions = session.scalars(select(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)).all()
            paper_orders = session.scalars(select(PaperFollowOrder).order_by(PaperFollowOrder.created_at_ms.desc()).limit(limit)).all()
            pnl_fills = session.scalars(select(Fill).where(Fill.closed_pnl.is_not(None)).order_by(Fill.exchange_ts.asc()).limit(500)).all()
            latest_market_snapshot = session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.id.desc()).limit(1)).first()
            repo = CollectionRepository(session)
            health_map = repo.get_source_health_map()
            latest_public_trade_event = session.scalars(
                select(RawEvent)
                .where(RawEvent.source == "hyperliquid_ws_public_trades")
                .order_by(RawEvent.fetched_at_ms.desc())
                .limit(1)
            ).first()

            public_trade_wallets_seen = int(
                session.scalar(
                    select(func.count(func.distinct(WalletCandidateModel.address))).where(
                        WalletCandidateModel.source_name == "public_trades_ws"
                    )
                )
                or 0
            )
            public_trade_promoted = int(
                session.scalar(
                    select(func.count()).select_from(TopWallet).where(TopWallet.source == "public_trades_ws")
                )
                or 0
            )
            fills_count = int(session.scalar(select(func.count()).select_from(Fill)) or 0)
            positions_count = int(session.scalar(select(func.count()).select_from(Position)) or 0)
            open_orders_count = int(session.scalar(select(func.count()).select_from(OpenOrder)) or 0)
        leaders = unique_top_wallets(leader_rows, limit=settings.copy_trading.top_leaders)
        leader_cards = [
            {
                "wallet_address": row.wallet_address,
                "rank": row.rank,
                "score": row.score,
                "source": row.source,
                "status": row.status,
                "notes": row.notes,
            }
            for row in leaders
        ]
        seen_leader_addresses = {row["wallet_address"].lower() for row in leader_cards}
        for row in leaderboard_candidate_rows:
            wallet_address = row.wallet_address.lower()
            if wallet_address in seen_leader_addresses:
                continue
            leader_cards.append(
                {
                    "wallet_address": row.wallet_address,
                    "rank": row.rank,
                    "score": row.leaderboard_score,
                    "source": "leaderboard_candidate",
                    "status": "selected_for_simulation_watch",
                    "notes": "complete_address_candidate;not_yet_promoted_to_top_wallet",
                }
            )
            seen_leader_addresses.add(wallet_address)
            if len(leader_cards) >= settings.copy_trading.top_leaders:
                break
        mid_prices = latest_mid_prices_from_snapshot(latest_market_snapshot.raw_json if latest_market_snapshot else None)
        public_trade_activity: list[dict[str, Any]] = []
        if latest_public_trade_event is not None:
            raw_public_payload = latest_public_trade_event.response_payload_json
            if not isinstance(raw_public_payload, list):
                payload_json = latest_public_trade_event.payload_json
                if isinstance(payload_json, dict) and isinstance(payload_json.get("trades"), list):
                    raw_public_payload = payload_json.get("trades")
            if isinstance(raw_public_payload, list):
                for trade in raw_public_payload[-20:]:
                    if not isinstance(trade, dict):
                        continue
                    coin = str(trade.get("coin") or "").upper()
                    price = safe_float(trade.get("px"))
                    size = safe_float(trade.get("sz"))
                    users = trade.get("users")
                    public_trade_activity.append(
                        {
                            "coin": coin,
                            "price": price,
                            "size": size,
                            "notional_usdc": round(abs(price * size), 6),
                            "trade_time_ms": trade.get("time"),
                            "users_count": len(users) if isinstance(users, list) else 0,
                            "source": "hyperliquid_ws_public_trades",
                            "read_only": True,
                        }
                    )
                public_trade_activity.reverse()
        live_simulation_deltas = [
            row
            for row in deltas
            if delta_event_time_ms(row) >= simulation_started_at_ms
        ]
        old_deltas_ignored = max(0, len(deltas) - len(live_simulation_deltas))
        last_live_event_ms = max((delta_event_time_ms(row) for row in live_simulation_deltas), default=None)
        seconds_since_last_live_event = (
            max(0, int((current_time_ms - last_live_event_ms) / 1000))
            if last_live_event_ms is not None
            else None
        )

        entry_deltas = []
        ignored_deltas = 0
        for row in live_simulation_deltas:
            action = copy_delta_action(row)
            direction = copy_delta_direction(row, action)
            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"} and direction is not None:
                entry_deltas.append(
                    {
                        "wallet_address": row.wallet_address,
                        "coin": row.coin,
                        "action": action,
                        "direction": direction,
                        "previous_size": row.previous_size,
                        "new_size": row.new_size,
                        "delta_size": row.delta_size,
                        "price": row.price,
                        "notional_usdc": row.delta_notional_usdc,
                        "confidence_score": row.confidence_score,
                        "detected_at_ms": row.detected_at_ms,
                        "research_only": True,
                    }
                )
            else:
                ignored_deltas += 1

        reasons: Counter[str] = Counter()
        for decision in decisions:
            if decision.allowed:
                continue
            for reason in decision.reasons_json or [decision.decision or "follow_decision_rejected"]:
                reasons[str(reason)] += 1
        if not leader_cards:
            reasons["NO_LEADER_WALLET_IMPORTED"] += 1
        if not deltas:
            reasons["NO_POSITION_DELTA_ANALYZED"] += 1
        if old_deltas_ignored:
            reasons["OLD_DELTA_IGNORED_FRESH_ONLY"] += old_deltas_ignored
        if not live_simulation_deltas and deltas:
            reasons["WAITING_FOR_FRESH_LEADER_EVENT"] += 1
        elif not entry_deltas and deltas:
            reasons["NO_ENTRY_DELTA_SIMULABLE"] += 1

        consensus = build_position_consensus(live_simulation_deltas, window_ms=300_000, min_wallets=2)
        bot_simulation = sim_engine.build_bot_simulation(
            live_simulation_deltas,
            mid_prices=mid_prices,
            now_timestamp_ms=current_time_ms,
            starting_equity_usdt=state.simulation_starting_equity_usdt,
            existing_positions=state.simulation_virtual_positions,
            existing_events=state.simulation_ledger_events,
            processed_delta_keys=state.simulation_processed_delta_keys,
            health_map=health_map,
        )
        state.simulation_virtual_positions = bot_simulation["virtual_positions_state"]
        state.simulation_ledger_events = bot_simulation["ledger_events"]
        state.simulation_processed_delta_keys = set(bot_simulation["processed_delta_keys"])
        persist_simulation_state(settings, state)
        for event in bot_simulation["events"]:
            if event.get("status") == "REFUSED" and event.get("reason"):
                for reason in str(event["reason"]).split("|"):
                    if reason:
                        reasons[reason] += 1
        chart_events = list(bot_simulation["ledger_events"])
        if bot_simulation.get("unrealized_pnl_usdc", 0.0) != 0 and chart_events:
            latest_event_ms = max((int(row.get("observed_at_ms") or 0) for row in chart_events), default=0)
            chart_events.append(
                {
                    "wallet_address": "virtual_portfolio",
                    "coin": "PORTFOLIO",
                    "observed_at_ms": latest_event_ms + 1,
                    "bot_replay_action": "MARK_TO_MARKET",
                    "estimated_net_pnl_usdc": bot_simulation.get("unrealized_pnl_usdc", 0.0),
                }
            )
        bot_candles = build_bot_equity_candles(chart_events)
        equity_candles = bot_candles
        equity_close = equity_candles[-1]["equity_close"] if equity_candles else 0.0
        equity_high = max((row["ha_high"] for row in equity_candles), default=0.0)
        equity_low = min((row["ha_low"] for row in equity_candles), default=0.0)
        simulation_poll_interval_seconds = min(settings.copy_trading.default_interval_seconds, 60)
        if not leader_cards:
            readiness = "IMPORT_OR_DISCOVERY_REQUIRED"
            next_step = "Importer jusqu'a 50 wallets complets ou laisser la discovery read-only remplir la shortlist; le logiciel ne cree pas de faux wallets."
        elif not deltas:
            readiness = "BACKFILL_OR_COPY_LOOP_REQUIRED"
            next_step = "Collecter positions/fills read-only pour ces wallets, puis reconstruire les deltas."
        elif not live_simulation_deltas:
            readiness = "WAITING_FOR_FRESH_EVENTS"
            next_step = (
                "Simulation armee: les anciennes ouvertures sont ignorees. "
                "Le P&L part de 0 et bougera seulement quand un leader ouvre, augmente, reduit ou ferme apres ce lancement."
            )
        elif not entry_deltas:
            readiness = "OBSERVATION_ONLY_NO_FRESH_ENTRY"
            next_step = (
                "Des evenements frais existent, mais aucun OPEN/ADD exploitable n'a passe les conditions. "
                "Les reductions/fermetures seules restent refusees sans position virtuelle locale."
            )
        else:
            readiness = "RESEARCH_SIMULATION_READY"
            next_step = "Comparer edge_remaining_bps, couts, delai et consensus avant toute simulation locale."

        source_health_data = [
            {
                "source": h.source_name,
                "last_event_ms": h.last_event_at_ms,
                "last_success_ms": h.last_success_at_ms,
                "seconds_since": h.seconds_since_last_event,
                "latency_ms": h.observed_latency_ms,
                "status": h.freshness_status,
                "is_consistent": h.is_consistent,
                "error": h.error_message,
            }
            for h in health_map.values()
        ]

        return {
            "mode": "LOCAL_RESEARCH_SIMULATION_ONLY",
            "paper_mock_usdc_only": True,
            "virtual_quote_asset": "USDT",
            "simulation_started_at_ms": simulation_started_at_ms,
            "simulation_started_iso_hint": "fresh_only_from_current_ui_process_start",
            "starting_equity_usdt": state.simulation_starting_equity_usdt,
            "no_real_orders": True,
            "no_testnet_executor": True,
            "no_profit_guarantee": True,
            "fresh_only": True,
            "fresh_cutoff_ms": simulation_started_at_ms,
            "simulation_state_persistent": True,
            "simulation_state_path": str(simulation_state_path(settings)),
            "simulation_ledger_events_count": len(state.simulation_ledger_events),
            "simulation_processed_deltas_count": len(state.simulation_processed_delta_keys),
            "current_time_ms": current_time_ms,
            "last_live_event_ms": last_live_event_ms,
            "seconds_since_last_live_event": seconds_since_last_live_event,
            "scanner": {
                "active": True,
                "target_wallets": settings.copy_trading.top_leaders,
                "candidate_pool_target": settings.wallet_bootstrap.target_wallets,
                "candidate_pool_max": settings.wallet_bootstrap.max_candidates_total,
                "active_leader_limit_reason": "bounded_read_only_api_limits",
                "polling_interval_seconds": simulation_poll_interval_seconds,
                "ui_refresh_seconds": 1,
                "mode": "read_only_polling_or_shortlist_ws",
                "public_trades_ws_enabled": True,
                "public_trade_coins": ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "ENA", "AVAX", "LINK"],
                "public_trade_wallets_seen": public_trade_wallets_seen,
                "public_trade_promoted_wallets": public_trade_promoted,
                "latest_public_trade_scan_ms": latest_public_trade_event.fetched_at_ms if latest_public_trade_event else None,
                "network_read_required_for_live_updates": True,
                "fresh_only": True,
                "old_history_ignored_for_pnl": True,
            },
            "autopilot": {
                "job_a": "leaderboard_discovery_shortlist",
                "job_b": "copy_loop_dry_run_observation",
                "job_c": "reports_dashboard_no_trade",
                "active_while_command_center_runs": True,
                "position_reproduction": "local_paper_research_only_after_edge_and_risk_gates",
                "execution": "forbidden",
            },
            "readiness": readiness,
            "next_step": next_step,
            "counts": {
                "leaders": len(leader_cards),
                "target_leaders": settings.copy_trading.top_leaders,
                "public_trade_wallets_seen": public_trade_wallets_seen,
                "public_trade_promoted_wallets": public_trade_promoted,
                "positions": positions_count,
                "fills": fills_count,
                "closed_pnl_points": len(pnl_fills),
                "open_orders_context": open_orders_count,
                "deltas": len(deltas),
                "live_simulation_deltas": len(live_simulation_deltas),
                "old_deltas_ignored_fresh_only": old_deltas_ignored,
                "entry_deltas": len(entry_deltas),
                "ignored_deltas": ignored_deltas,
                "consensus_positions": len(consensus),
                "bot_decision_events": len(bot_simulation["events"]),
                "reproduced_entries": bot_simulation["reproduced_entries"],
                "reproduced_exits": bot_simulation["reproduced_exits"],
                "bot_refused": bot_simulation["refused"],
                "open_virtual_positions": bot_simulation["open_local_positions"],
                "follow_decisions": len(decisions),
                "paper_simulations": len(paper_orders),
                "magic_entries": bot_simulation["reproduced_entries"],
                "magic_exits": bot_simulation["reproduced_exits"],
                "magic_refusals": bot_simulation["refused"],
            },
            "equity": {
                "current_pnl_usdc": bot_simulation.get("estimated_net_pnl_usdc", 0.0) if bot_candles else round(float(equity_close), 6),
                "starting_equity_usdt": state.simulation_starting_equity_usdt,
                "current_equity_usdt": round(state.simulation_starting_equity_usdt + float(bot_simulation.get("estimated_net_pnl_usdc", 0.0) if bot_candles else 0.0), 6),
                "realized_pnl_usdc": bot_simulation.get("realized_net_pnl_usdc", 0.0),
                "unrealized_pnl_usdc": bot_simulation.get("unrealized_pnl_usdc", 0.0),
                "high_pnl_usdc": round(float(equity_high), 6),
                "low_pnl_usdc": round(float(equity_low), 6),
                "candles_count": len(equity_candles),
                "source": "fresh bot virtual portfolio simulation from deltas detected after simulation start",
                "bot_net_pnl_usdc": bot_simulation.get("estimated_net_pnl_usdc", 0.0),
                "bot_cost_model_bps": bot_simulation["cost_model_bps"],
                "bot_costs_paid_usdc": bot_simulation["total_costs_paid_usdc"],
            },
            "equity_candles": equity_candles,
            "bot_simulation": bot_simulation,
            "magic_profile": bot_simulation["magic_profile"],
            "reproduction": bot_simulation,
            "leaders": leader_cards,
            "source_health": source_health_data,
            "entry_deltas": entry_deltas[:25],
            "consensus": consensus[:10],
            "public_trade_activity": public_trade_activity[:12],
            "no_trade_reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common()],
            "paper_simulations": [
                {
                    "id": row.id,
                    "signal_id": row.signal_id,
                    "wallet_address": row.wallet_address,
                    "coin": row.coin,
                    "side": row.side,
                    "notional_usdc": row.notional_usdc,
                    "status": row.status,
                    "created_at_ms": row.created_at_ms,
                }
                for row in paper_orders[:25]
            ],
            "message": "Simulation locale seulement. Le graphe ignore l'ancien historique; il bouge uniquement sur evenements frais. Aucun profit futur n'est garanti.",
        }

    @router.get("/api/logs", response_model=list[UiLogLine])
    async def logs() -> list[UiLogLine]:
        return state.logs[-200:]

    @router.get("/api/events/recent")
    async def events_recent() -> list[dict[str, Any]]:
        events = state.events[-100:]
        raw_events: list[dict[str, Any]] = [event.model_dump() for event in events]
        try:
            with session_factory() as session:
                db_events = session.scalars(select(RawEvent).order_by(RawEvent.id.desc()).limit(20)).all()
                raw_events.extend(
                    {
                        "event_type": "raw_event_stored",
                        "message": f"{event.request_type} stored",
                        "level": "INFO",
                        "timestamp_ms": event.fetched_at_ms,
                        "payload": {
                            "request_type": event.request_type,
                            "coin": event.coin,
                            "wallet_address": event.wallet_address,
                            "success": event.success,
                        },
                    }
                    for event in db_events
                )
        except SQLAlchemyError:
            pass
        return raw_events

    @router.get("/api/simple-home")
    async def simple_home() -> dict[str, Any]:
        discovery = _discovery_summary()
        market = _market_summary()
        leaderboard = _leaderboard_summary()
        explorer = _explorer_summary()
        return {
            "title": "Recherche automatique des meilleurs wallets",
            "subtitle": (
                "Le logiciel cherche automatiquement les meilleurs wallets Hyperliquid, notamment via le leaderboard, "
                "puis analyse positions, ouvertures, fermetures, profits, altcoins, methodologies et signaux paper."
            ),
            "mode": settings.environment.value.upper(),
            "autoscan": _autoscan_summary(),
            "market_universe_summary": market,
            "coins_discovered": market["coins_discovered"],
            "coins_scanned": market["coins_scanned"],
            "altcoins_enabled": market["altcoins_enabled"],
            "top_coins": market["top_coins"],
            "coin_opportunities": market["coin_opportunities"],
            "wallets_positive_pnl_by_coin": market["wallets_positive_pnl_by_coin"],
            "selected_wallets_by_coin": discovery["selected_wallets_by_coin"],
            "simple_cards": {
                "sources": {
                    "leaderboard_status": leaderboard["status"],
                    "explorer_status": explorer["status"],
                    "imports_available": True,
                    "local_db_available": True,
                    "sources_attempted": discovery["sources_attempted"],
                    "source_errors": discovery["errors_count"] + (1 if explorer["status"] in {"NETWORK_FAILED", "SOURCE_UNAVAILABLE", "IMPORT_REQUIRED"} else 0),
                    "next_action": explorer["next_action"] if explorer["candidates_created"] == 0 and discovery["candidates_found"] == 0 else "scan_wallet_queue",
                },
                "market": market,
                "leaderboard": leaderboard,
                "explorer": explorer,
                "discovery": discovery,
                "intelligence": _intelligence_summary(),
                "best_wallets": {
                    "positive_pnl": discovery["candidates_positive_pnl"],
                    "positive_roi": discovery["candidates_positive_roi"],
                    "backfilled": _count_backfilled_selected(),
                    "positive_altcoin_wallets": market["wallets_positive_pnl_altcoins"],
                    "best_coin": market["best_coin"],
                    "top_wallet": market["top_wallet"],
                },
                "security": {
                    "read_only": True,
                    "mainnet_forbidden": not settings.execution.enable_mainnet_execution,
                    "testnet_locked": not settings.execution.enable_testnet_execution,
                    "kill_switch": state.kill_switch_active,
                },
            },
            "manual_wallet_secondary": True,
            "truncated_addresses_message": (
                "Certaines adresses du leaderboard sont tronquees. Elles sont ignorees tant que le logiciel ne recupere pas l'adresse complete. Aucun wallet n'est invente."
            ),
            "discovery_empty_state": _discovery_empty_state(discovery),
        }

    @router.get("/api/markets/universe")
    async def markets_universe(limit: int = 200) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(MarketUniverseModel).order_by(MarketUniverseModel.coin.asc()).limit(limit)
            ).all()
        return [
            {
                "coin": row.coin,
                "source": row.source,
                "is_active": row.is_active,
                "is_spot": row.is_spot,
                "first_seen_ms": row.first_seen_ms,
                "last_seen_ms": row.last_seen_ms,
                "mid_price": row.mid_price,
                "notes": row.notes,
            }
            for row in rows
        ]

    @router.get("/api/markets/metrics")
    async def markets_metrics(limit: int = 200) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(MarketMetric).order_by(MarketMetric.id.desc()).limit(limit)).all()
        return [
            {
                "coin": row.coin,
                "computed_at_ms": row.computed_at_ms,
                "mid_price": row.mid_price,
                "spread_bps": row.spread_bps,
                "depth_usdc": row.depth_usdc,
                "liquidity_score": row.liquidity_score,
                "is_scannable": row.is_scannable,
                "rejection_reason": row.rejection_reason,
            }
            for row in rows
        ]

    @router.get("/api/markets/opportunities")
    async def market_opportunities(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(CoinOpportunity).order_by(CoinOpportunity.opportunity_score.desc()).limit(limit)).all()
        return [
            {
                "coin": row.coin,
                "wallets_active": row.wallets_active,
                "wallets_positive_pnl": row.wallets_positive_pnl,
                "wallets_positive_roi": row.wallets_positive_roi,
                "best_wallet_address": row.best_wallet_address,
                "best_wallet_score": row.best_wallet_score,
                "liquidity_score": row.liquidity_score,
                "spread_bps": row.spread_bps,
                "opportunity_score": row.opportunity_score,
                "status": row.status,
                "notes": row.notes,
            }
            for row in rows
        ]

    @router.get("/api/discovery/status")
    async def discovery_status() -> dict[str, Any]:
        return _discovery_summary()

    @router.post("/api/discovery/start")
    async def discovery_start() -> dict[str, Any]:
        result = await run_safe_action("discover_wallets", settings, state)
        await bus.broadcast(
            state.add_event(
                "wallet_discovery_completed",
                result.message,
                level=result.level,
                payload=result.details,
            )
        )
        return result.model_dump()

    @router.get("/api/discovery/candidates")
    async def discovery_candidates(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(WalletCandidateModel).order_by(WalletCandidateModel.id.desc()).offset(offset).limit(limit)
            ).all()
            score_by_wallet = {
                score.wallet_address: score
                for score in session.scalars(
                    select(WalletCandidateScoreModel)
                    .order_by(WalletCandidateScoreModel.id.desc())
                    .limit(max(limit * 2, 100))
                ).all()
            }
        return [
            {
                "address": row.address,
                "coin": row.coin,
                "source": row.source_name,
                "external_pnl_usdc": row.external_pnl_usdc,
                "external_roi_pct": row.external_roi_pct,
                "discovery_score": (
                    score_by_wallet[row.address].final_discovery_score
                    if row.address in score_by_wallet
                    else row.confidence_score * 100
                ),
                "decision": (
                    score_by_wallet[row.address].decision if row.address in score_by_wallet else "DISCOVERED"
                ),
                "reasons": (
                    score_by_wallet[row.address].reasons_json if row.address in score_by_wallet else []
                ),
                "selected_for_backfill": row.selected_for_backfill,
                "rejection_reason": row.rejection_reason,
            }
            for row in rows
        ]

    @router.get("/api/discovery/selected")
    async def discovery_selected() -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(AutoWatchlist).order_by(AutoWatchlist.discovery_score.desc()).limit(100)).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "label": row.label,
                "source": row.source,
                "discovery_score": row.discovery_score,
                "status": row.status,
                "last_backfill_ms": row.last_backfill_ms,
                "notes": row.notes,
            }
            for row in rows
        ]

    @router.get("/api/wallets/top-by-coin")
    async def wallets_top_by_coin(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(WalletCoinScoreModel).order_by(WalletCoinScoreModel.final_score.desc()).limit(limit)
            ).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "final_score": row.final_score,
                "decision": row.decision,
                "reasons": row.reasons_json,
            }
            for row in rows
        ]

    @router.get("/api/wallets/{wallet_address}/coins")
    async def wallet_coins(wallet_address: str) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(WalletCoinProfileModel)
                .where(WalletCoinProfileModel.wallet_address == wallet_address)
                .order_by(WalletCoinProfileModel.final_coin_score.desc())
                .limit(100)
            ).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "fills_count": row.fills_count,
                "deltas_count": row.deltas_count,
                "estimated_pnl_usdc": row.estimated_pnl_usdc,
                "estimated_roi_pct": row.estimated_roi_pct,
                "copyability_score": row.copyability_score,
                "liquidity_score": row.liquidity_score,
                "final_coin_score": row.final_coin_score,
                "status": row.status,
            }
            for row in rows
        ]

    @router.post("/api/discovery/backfill-selected")
    async def discovery_backfill_selected() -> dict[str, Any]:
        result = await run_safe_action("backfill_selected_wallets", settings, state)
        await bus.broadcast(
            state.add_event(
                "selected_wallet_backfill_started",
                result.message,
                level=result.level,
                payload=result.details,
            )
        )
        return result.model_dump()

    @router.get("/api/autoscan/status")
    async def autoscan_status() -> dict[str, Any]:
        resolved_state = _resolved_autoscan_state()
        return {
            "running": state.discovery_running or state.autoscan_running,
            "started": state.autoscan_started,
            "state": resolved_state,
            "current_step": state.autoscan_current_step,
            "progress_percent": state.autoscan_progress_percent,
            "summary": state.last_autoscan_summary,
            "kill_switch": state.kill_switch_active,
        }

    @router.get("/api/autoscan/progress")
    async def autoscan_progress() -> dict[str, Any]:
        discovery = _discovery_summary()
        market = _market_summary()
        return {
            "steps": [
                "Demarrage",
                "Securite",
                "Decouverte marches",
                "Prix tous coins",
                "Coins liquides",
                "Lecture leaderboard",
                "Validation adresses",
                "Recherche wallets",
                "Filtre PnL/ROI",
                "Top 500",
                "File de scan wallets",
                "Backfill multi-coins",
                "Deltas par coin",
                "Ouvertures detectees",
                "Fermetures detectees",
                "Profits analyses",
                "Methodologies classees",
                "Signaux de suivi",
                "Filtre de risque",
                "Resume",
            ],
            "state": _resolved_autoscan_state(),
            "market": market,
            "discovery": discovery,
        }

    @router.post("/api/autoscan/stop")
    async def autoscan_stop() -> dict[str, Any]:
        result = await run_safe_action("autoscan_stop", settings, state)
        return result.model_dump()

    @router.post("/api/autoscan/start")
    async def autoscan_start() -> dict[str, Any]:
        if state.discovery_running:
            return {"running": True, "message": "Recherche automatique deja en cours."}
        state.discovery_running = True
        state.autoscan_started = True
        try:
            result = await run_safe_action("autoscan_with_discovery", settings, state)
            await bus.broadcast(
                state.add_event(
                    "wallet_discovery_completed",
                    result.message,
                    level=result.level,
                    payload=result.details,
                )
            )
            return result.model_dump()
        finally:
            state.discovery_running = False

    @router.get("/api/leaderboard/status")
    async def leaderboard_status() -> dict[str, Any]:
        with session_factory() as session:
            run = session.scalar(select(LeaderboardRun).order_by(desc(LeaderboardRun.id)).limit(1))
            full = int(session.scalar(select(func.count()).select_from(LeaderboardWalletCandidate)) or 0)
            truncated = int(
                session.scalar(
                    select(func.count())
                    .select_from(LeaderboardAddressValidation)
                    .where(LeaderboardAddressValidation.is_truncated.is_(True))
                )
                or 0
            )
        return {
            "source": "https://app.hyperliquid.xyz/leaderboard",
            "priority": "primary",
            "status": run.status if run else "IMPORT_REQUIRED",
            "period": run.period if run else "30D",
            "rows_seen": run.rows_seen if run else 0,
            "full_addresses_found": run.full_addresses_found if run else full,
            "truncated_addresses_rejected": run.truncated_addresses_seen if run else truncated,
            "candidates_created": run.candidates_created if run else full,
            "message": "Certaines adresses du leaderboard sont tronquees. Elles sont ignorees tant que le logiciel ne recupere pas l'adresse complete. Aucun wallet n'est invente.",
        }

    @router.get("/api/leaderboard/rows")
    async def leaderboard_rows(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(LeaderboardRow).order_by(LeaderboardRow.id.desc()).limit(limit)).all()
        return [
            {
                "rank": row.rank,
                "address": row.address,
                "address_short": row.address_short,
                "address_is_full": row.address_is_full,
                "account_value_usdc": row.account_value_usdc,
                "pnl_usdc": row.pnl_usdc,
                "roi_pct": row.roi_pct,
                "volume_usdc": row.volume_usdc,
                "validation_status": row.validation_status,
                "rejection_reason": row.rejection_reason,
            }
            for row in rows
        ]

    @router.get("/api/leaderboard/candidates")
    async def leaderboard_candidates(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(LeaderboardWalletCandidate).order_by(LeaderboardWalletCandidate.leaderboard_score.desc()).limit(limit)
            ).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "rank": row.rank,
                "period": row.period,
                "account_value_usdc": row.account_value_usdc,
                "pnl_usdc": row.pnl_usdc,
                "roi_pct": row.roi_pct,
                "volume_usdc": row.volume_usdc,
                "leaderboard_score": row.leaderboard_score,
                "selected_for_backfill": row.selected_for_backfill,
            }
            for row in rows
        ]

    @router.get("/api/leaderboard/rejected")
    async def leaderboard_rejected(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(LeaderboardAddressValidation)
                .where(LeaderboardAddressValidation.is_full_address.is_(False))
                .order_by(LeaderboardAddressValidation.id.desc())
                .limit(limit)
            ).all()
        return [
            {
                "raw_value": row.raw_value,
                "status": row.validation_status,
                "rejection_reason": row.rejection_reason,
                "is_truncated": row.is_truncated,
            }
            for row in rows
        ]

    @router.post("/api/leaderboard/scrape")
    async def leaderboard_scrape() -> dict[str, Any]:
        return (await run_safe_action("scrape_leaderboard", settings, state)).model_dump()

    @router.post("/api/leaderboard/probe-network")
    async def leaderboard_probe_network() -> dict[str, Any]:
        return (await run_safe_action("probe_leaderboard_network", settings, state)).model_dump()

    @router.post("/api/leaderboard/extract-dom")
    async def leaderboard_extract_dom() -> dict[str, Any]:
        return (await run_safe_action("extract_leaderboard_dom", settings, state)).model_dump()

    @router.post("/api/leaderboard/import")
    async def leaderboard_import() -> dict[str, Any]:
        return (await run_safe_action("import_leaderboard", settings, state)).model_dump()

    @router.post("/api/leaderboard/validate-addresses")
    async def leaderboard_validate() -> dict[str, Any]:
        return (await run_safe_action("validate_leaderboard_addresses", settings, state)).model_dump()

    @router.get("/api/explorer/status")
    async def explorer_status() -> dict[str, Any]:
        return _explorer_summary()

    @router.get("/api/explorer/events")
    async def explorer_events(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(ExplorerEvent).order_by(ExplorerEvent.id.desc()).limit(limit)).all()
        return [
            {
                "event_type": row.event_type,
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "status": row.status,
                "raw": row.raw_json,
            }
            for row in rows
        ]

    @router.get("/api/explorer/transactions")
    async def explorer_transactions(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(ExplorerTransactionTape).order_by(ExplorerTransactionTape.id.desc()).limit(limit)).all()
        return [
            {
                "tx_hash": row.tx_hash,
                "block": row.block,
                "action_type": row.action_type,
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "value_usdc": row.value_usdc,
                "status": row.status,
                "candidate_created": row.candidate_created,
                "reason": row.reason,
            }
            for row in rows
        ]

    @router.get("/api/explorer/candidates")
    async def explorer_candidates(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(ExplorerWalletCandidate).order_by(ExplorerWalletCandidate.activity_score.desc()).limit(limit)
            ).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "source": row.source,
                "first_tx_hash": row.first_tx_hash,
                "events_count": row.events_count,
                "coins": row.coins_json,
                "activity_score": row.activity_score,
                "validation_status": row.validation_status,
            }
            for row in rows
        ]

    @router.get("/api/explorer/rejected")
    async def explorer_rejected(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(ExplorerTransaction)
                .where(ExplorerTransaction.validation_status != "FULL_ADDRESS_OK")
                .order_by(ExplorerTransaction.id.desc())
                .limit(limit)
            ).all()
        return [
            {
                "tx_hash": row.tx_hash,
                "address_short": row.address_short,
                "status": row.validation_status,
                "reason": row.validation_status,
            }
            for row in rows
        ]

    @router.get("/api/explorer/revalidation-results")
    async def explorer_revalidation_results(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(ExplorerRevalidationResult).order_by(ExplorerRevalidationResult.id.desc()).limit(limit)
            ).all()
        return [
            {
                "wallet_address": row.wallet_address,
                "ok": row.ok,
                "method": row.method,
                "checked_at_ms": row.checked_at_ms,
                "error_message": row.error_message,
            }
            for row in rows
        ]

    @router.post("/api/explorer/probe")
    async def explorer_probe() -> dict[str, Any]:
        return (await run_safe_action("probe_explorer", settings, state)).model_dump()

    @router.post("/api/explorer/scrape")
    async def explorer_scrape() -> dict[str, Any]:
        return (await run_safe_action("scrape_explorer", settings, state)).model_dump()

    @router.post("/api/explorer/import")
    async def explorer_import() -> dict[str, Any]:
        return (await run_safe_action("import_explorer", settings, state)).model_dump()

    @router.post("/api/explorer/candidates")
    async def explorer_create_candidates() -> dict[str, Any]:
        return (await run_safe_action("explorer_candidates", settings, state)).model_dump()

    @router.post("/api/explorer/revalidate-wallets")
    async def explorer_revalidate_wallets() -> dict[str, Any]:
        return (await run_safe_action("revalidate_explorer_wallets", settings, state)).model_dump()

    @router.get("/api/top-wallets/status")
    async def top_wallets_status() -> dict[str, Any]:
        with session_factory() as session:
            run = session.scalar(select(WalletBootstrapRun).order_by(desc(WalletBootstrapRun.id)).limit(1))
            count = int(session.scalar(select(func.count()).select_from(TopWallet)) or 0)
        return {
            "target": settings.wallet_bootstrap.target_wallets,
            "wallets_available": count,
            "status": run.status if run else ("INCOMPLETE" if count < settings.wallet_bootstrap.target_wallets else "COMPLETE"),
            "honest_incomplete": count < settings.wallet_bootstrap.target_wallets,
        }

    @router.get("/api/top-wallets")
    async def top_wallets(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(TopWallet).order_by(TopWallet.score.desc()).limit(limit)).all()
        return [
            {"wallet_address": row.wallet_address, "rank": row.rank, "source": row.source, "score": row.score, "status": row.status}
            for row in rows
        ]

    @router.get("/api/top-wallets/sources")
    async def top_wallet_sources(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(TopWalletSource).order_by(TopWalletSource.source_score.desc()).limit(limit)).all()
        return [
            {"wallet_address": row.wallet_address, "source": row.source, "source_rank": row.source_rank, "source_score": row.source_score}
            for row in rows
        ]

    @router.get("/api/top-wallets/rejected")
    async def top_wallets_rejected() -> dict[str, Any]:
        return {"items": [], "message": "Aucun wallet tronque ou invente n'est admis dans top_wallets."}

    @router.post("/api/top-wallets/bootstrap")
    async def top_wallets_bootstrap() -> dict[str, Any]:
        return (await run_safe_action("bootstrap_top_wallets", settings, state)).model_dump()

    @router.post("/api/top-wallets/export")
    async def top_wallets_export() -> dict[str, Any]:
        return (await run_safe_action("export_top_wallets", settings, state)).model_dump()

    @router.get("/api/candidates/summary")
    async def candidates_summary() -> dict[str, Any]:
        discovery = _discovery_summary()
        return {
            "candidates": discovery["candidates_found"],
            "selected": discovery["selected_wallets"],
            "rejected": max(0, discovery["candidates_found"] - discovery["selected_wallets"]),
            "positive_pnl": discovery["candidates_positive_pnl"],
            "positive_roi": discovery["candidates_positive_roi"],
        }

    @router.get("/api/candidates")
    async def candidates_all(limit: int = 100) -> list[dict[str, Any]]:
        return await discovery_candidates(limit=limit, offset=0)

    @router.get("/api/candidates/selected")
    async def candidates_selected() -> list[dict[str, Any]]:
        return await discovery_selected()

    @router.get("/api/candidates/rejected")
    async def candidates_rejected(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(
                select(WalletCandidateModel)
                .where(WalletCandidateModel.rejection_reason.is_not(None))
                .order_by(WalletCandidateModel.id.desc())
                .limit(limit)
            ).all()
        return [{"address": row.address, "coin": row.coin, "reason": row.rejection_reason, "source": row.source_name} for row in rows]

    @router.get("/api/candidates/{wallet_address}")
    async def candidate_detail(wallet_address: str) -> dict[str, Any]:
        with session_factory() as session:
            row = session.scalar(select(WalletCandidateModel).where(WalletCandidateModel.address == wallet_address).order_by(desc(WalletCandidateModel.id)).limit(1))
        if row is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        return {"address": row.address, "coin": row.coin, "source": row.source_name, "selected_for_backfill": row.selected_for_backfill, "rejection_reason": row.rejection_reason}

    @router.get("/api/openings/summary")
    async def openings_summary() -> dict[str, Any]:
        return {"openings": safe_count(WalletOpening), "patterns": safe_count(WalletOpeningPatternStats)}

    @router.get("/api/openings/patterns")
    async def openings_patterns(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletOpeningPatternStats).order_by(WalletOpeningPatternStats.opening_pattern_score.desc()).limit(limit)).all()
        return [{"opening_type": row.opening_type, "sample_size": row.sample_size, "win_rate": row.win_rate, "expectancy": row.expectancy, "profit_factor": row.profit_factor, "score": row.opening_pattern_score, "decision": row.decision} for row in rows]

    @router.get("/api/openings/top-profitable")
    async def openings_top_profitable(limit: int = 50) -> list[dict[str, Any]]:
        return await openings_patterns(limit=limit)

    @router.get("/api/openings/by-wallet/{wallet}")
    async def openings_by_wallet(wallet: str) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletOpening).where(WalletOpening.wallet_address == wallet).limit(100)).all()
        return [{"wallet_address": row.wallet_address, "coin": row.coin, "opening_type": row.opening_type, "confidence_score": row.confidence_score} for row in rows]

    @router.get("/api/openings/by-coin/{coin}")
    async def openings_by_coin(coin: str) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletOpening).where(WalletOpening.coin == coin.upper()).limit(100)).all()
        return [{"wallet_address": row.wallet_address, "coin": row.coin, "opening_type": row.opening_type, "confidence_score": row.confidence_score} for row in rows]

    @router.get("/api/openings/rejected")
    async def openings_rejected(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletOpeningPatternStats).where(WalletOpeningPatternStats.decision.like("REJECT%")).limit(limit)).all()
        return [{"opening_type": row.opening_type, "decision": row.decision, "reasons": row.reasons_json} for row in rows]

    @router.get("/api/playbooks/summary")
    async def playbooks_summary() -> dict[str, Any]:
        return {"profiles": safe_count(WalletMethodologyProfile), "playbooks": safe_count(WalletPlaybook)}

    @router.get("/api/playbooks")
    async def playbooks(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletPlaybook).order_by(WalletPlaybook.confidence_score.desc()).limit(limit)).all()
        return [{"wallet_address": row.wallet_address, "coin": row.coin, "playbook_type": row.playbook_type, "rule_summary": row.rule_summary, "confidence_score": row.confidence_score, "status": row.status} for row in rows]

    @router.get("/api/playbooks/{wallet_address}")
    async def playbook_detail(wallet_address: str) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(WalletPlaybook).where(WalletPlaybook.wallet_address == wallet_address).limit(100)).all()
        return [{"coin": row.coin, "rule_summary": row.rule_summary, "opening_rules": row.opening_rules_json, "closing_rules": row.closing_rules_json, "risk_rules": row.risk_rules_json, "status": row.status} for row in rows]

    @router.get("/api/follow-signals/summary")
    async def follow_signals_summary() -> dict[str, Any]:
        return {
            "signals": safe_count(FollowSignal),
            "decisions": safe_count(FollowDecision),
            "paper_orders": safe_count(PaperFollowOrder),
        }

    @router.get("/api/follow-signals")
    async def follow_signals(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(FollowSignal).order_by(FollowSignal.created_at_ms.desc()).limit(limit)).all()
        return [{"id": row.id, "wallet_address": row.wallet_address, "coin": row.coin, "side": row.side, "opening_type": row.opening_type, "signal_age_ms": row.signal_age_ms} for row in rows]

    @router.get("/api/follow-signals/allowed")
    async def follow_signals_allowed(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(FollowDecision).where(FollowDecision.allowed.is_(True)).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)).all()
        return [{"signal_id": row.signal_id, "decision": row.decision, "risk_level": row.risk_level, "reasons": row.reasons_json} for row in rows]

    @router.get("/api/follow-signals/rejected")
    async def follow_signals_rejected(limit: int = 100) -> list[dict[str, Any]]:
        with session_factory() as session:
            rows = session.scalars(select(FollowDecision).where(FollowDecision.allowed.is_(False)).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)).all()
        return [{"signal_id": row.signal_id, "decision": row.decision, "risk_level": row.risk_level, "reasons": row.reasons_json} for row in rows]

    @router.get("/api/follow-signals/{signal_id}")
    async def follow_signal_detail(signal_id: str) -> dict[str, Any]:
        with session_factory() as session:
            signal = session.get(FollowSignal, signal_id)
        if signal is None:
            raise HTTPException(status_code=404, detail="follow signal not found")
        return {"id": signal.id, "wallet_address": signal.wallet_address, "coin": signal.coin, "opening_type": signal.opening_type, "raw": signal.raw_json}

    @router.post("/api/wallets/analyze")
    async def wallets_analyze() -> dict[str, Any]:
        return (await run_safe_action("analyze_wallet", settings, state)).model_dump()

    @router.get("/api/actions/catalog")
    async def actions_catalog() -> list[dict[str, Any]]:
        allowed = set(__import__("hl_observer.ui.safe_actions", fromlist=["ALLOWED_ACTIONS"]).ALLOWED_ACTIONS)
        return [
            item.model_dump()
            for item in build_action_catalog()
            if item.action_id in allowed
        ]

    @router.get("/api/actions/status")
    async def actions_status() -> dict[str, Any]:
        return {"kill_switch_active": state.kill_switch_active, "allowlist_active": True}

    @router.get("/api/help/glossary")
    async def help_glossary() -> dict[str, str]:
        return {
            "leaderboard": "Source publique prioritaire; seules les adresses completes sont exploitables.",
            "adresse tronquee": "Adresse contenant ...; elle est toujours rejetee.",
            "paper": "Simulation locale sans ordre reel.",
            "edge": "Estimation prudente du potentiel restant apres couts.",
            "playbook": "Resume observe-only d'une methodologie wallet, jamais une promesse.",
        }

    @router.post("/api/actions")
    async def actions(request: UiActionRequest) -> dict[str, Any]:
        if request.action == "reset_simulation_session":
            state.simulation_started_at_ms = now_ms()
            state.simulation_starting_equity_usdt = 1000.0
            state.simulation_processed_delta_keys.clear()
            state.simulation_virtual_positions.clear()
            state.simulation_ledger_events.clear()
            persist_simulation_state(settings, state)
            result_payload = {
                "action": request.action,
                "allowed": True,
                "success": True,
                "level": "INFO",
                "message": "Session simulation remise a zero localement. Aucun ordre cree.",
                "details": {
                    "simulation_started_at_ms": state.simulation_started_at_ms,
                    "state_path": str(simulation_state_path(settings)),
                    "no_real_orders": True,
                },
            }
            await bus.broadcast(
                state.add_event(
                    "simulation_session_reset",
                    result_payload["message"],
                    payload=result_payload["details"],
                )
            )
            return result_payload
        result = await run_safe_action(request.action, settings, state)
        await bus.broadcast(
            state.add_event(
                "ui_action",
                result.message,
                level=result.level,
                payload={"action": request.action, "success": result.success},
            )
        )
        if not result.allowed:
            return result.model_dump()
        return result.model_dump()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await bus.connect(websocket)
        try:
            await websocket.send_json(
                {
                    "event_type": "heartbeat",
                    "message": "Connexion locale au cockpit etablie.",
                    "level": "INFO",
                    "timestamp_ms": now_ms(),
                    "payload": {"kill_switch_active": state.kill_switch_active},
                }
            )
            for event in state.events[-25:]:
                await websocket.send_json(event.model_dump())
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            bus.disconnect(websocket)
        except RuntimeError:
            bus.disconnect(websocket)

    def _discovery_summary() -> dict[str, Any]:
        last_run_at_ms = None
        sources_attempted = 0
        candidates_found = 0
        selected_wallets = 0
        errors_count = 0
        last_error = None
        candidates_positive_pnl = 0
        candidates_positive_roi = 0
        try:
            with session_factory() as session:
                run = session.scalar(select(WalletDiscoveryRun).order_by(desc(WalletDiscoveryRun.id)).limit(1))
                if run is not None:
                    last_run_at_ms = run.finished_at_ms or run.started_at_ms
                    sources_attempted = run.sources_attempted
                    candidates_found = run.candidates_found
                    selected_wallets = run.wallets_selected
                    errors_count = run.errors_count
                candidates_positive_pnl = int(
                    session.scalar(
                        select(func.count())
                        .select_from(WalletCandidateModel)
                        .where(WalletCandidateModel.external_pnl_usdc > 0)
                    )
                    or 0
                )
                candidates_positive_roi = int(
                    session.scalar(
                        select(func.count())
                        .select_from(WalletCandidateModel)
                        .where(WalletCandidateModel.external_roi_pct > 0)
                    )
                    or 0
                )
                failed = session.scalar(
                    select(WalletDiscoverySourceModel.error_message)
                    .where(WalletDiscoverySourceModel.error_message.is_not(None))
                    .order_by(WalletDiscoverySourceModel.id.desc())
                    .limit(1)
                )
                last_error = failed
        except SQLAlchemyError as exc:
            last_error = str(exc)
        return {
            "enabled": settings.wallet_discovery.enabled,
            "running": state.discovery_running,
            "last_run_at_ms": last_run_at_ms,
            "sources_attempted": sources_attempted,
            "candidates_found": candidates_found,
            "candidates_positive_pnl": candidates_positive_pnl,
            "candidates_positive_roi": candidates_positive_roi,
            "selected_wallets": selected_wallets,
            "backfilled_wallets": _count_backfilled_selected(),
            "errors_count": errors_count,
            "last_error": last_error,
            "state": state.last_discovery_state,
            "candidates_count": candidates_found,
            "selected_wallets_count": selected_wallets,
            "positive_pnl_count": candidates_positive_pnl,
            "positive_roi_count": candidates_positive_roi,
                "backfilled_wallets_count": _count_backfilled_selected(),
                "selected_wallets_by_coin": _selected_wallets_by_coin(),
            }

    def _has_raw_event(request_type: str) -> bool:
        try:
            with session_factory() as session:
                return bool(
                    session.scalar(
                        select(func.count()).select_from(RawEvent).where(RawEvent.request_type == request_type)
                    )
                )
        except SQLAlchemyError:
            return False

    def _count_backfilled_selected() -> int:
        try:
            with session_factory() as session:
                return int(
                    session.scalar(
                        select(func.count())
                        .select_from(AutoWatchlist)
                        .where(AutoWatchlist.last_backfill_ms.is_not(None))
                    )
                    or 0
                )
        except SQLAlchemyError:
            return 0

    def _discovery_empty_state(discovery: dict[str, Any]) -> str:
        if discovery["candidates_found"] == 0:
            return "Aucun wallet exploitable trouve automatiquement pour le moment."
        if discovery["selected_wallets"] == 0:
            return "Des wallets ont ete trouves, mais aucun ne passe encore les filtres PnL/ROI/activite."
        if discovery["backfilled_wallets"] == 0:
            return "Des wallets sont selectionnes. Le backfill va demarrer ou a ete limite par la configuration."
        return "Les meilleurs wallets ont ete analyses."

    def _market_summary() -> dict[str, Any]:
        try:
            with session_factory() as session:
                coins_discovered = int(session.scalar(select(func.count()).select_from(MarketUniverseModel)) or 0)
                coins_scanned = int(session.scalar(select(func.count(func.distinct(MarketMetric.coin)))) or 0)
                carnets = int(session.scalar(select(func.count()).select_from(RawEvent).where(RawEvent.request_type == "l2Book")) or 0)
                top_metric = session.scalar(select(MarketMetric).order_by(MarketMetric.liquidity_score.desc()).limit(1))
                top_scores = session.scalars(
                    select(WalletCoinScoreModel).order_by(WalletCoinScoreModel.final_score.desc()).limit(5)
                ).all()
                positive_by_coin_rows = session.query(
                    WalletCoinProfileModel.coin,
                    func.count(WalletCoinProfileModel.id),
                ).filter(
                    WalletCoinProfileModel.estimated_pnl_usdc > 0
                ).group_by(WalletCoinProfileModel.coin).all()
        except SQLAlchemyError:
            coins_discovered = 0
            coins_scanned = 0
            carnets = 0
            top_metric = None
            top_scores = []
            positive_by_coin_rows = []
        positive_by_coin = {coin: int(count) for coin, count in positive_by_coin_rows}
        top_coins = [
            {"coin": row.coin, "wallet": row.wallet_address, "score": row.final_score}
            for row in top_scores
        ]
        best = top_scores[0] if top_scores else None
        altcoin_positive = sum(count for coin, count in positive_by_coin.items() if coin not in {"BTC", "ETH"})
        return {
            "price_ok": _has_raw_event("allMids"),
            "coins_discovered": coins_discovered,
            "coins_scanned": coins_scanned,
            "altcoins_enabled": settings.market_universe.altcoins_enabled,
            "best_coin": best.coin if best is not None else (top_metric.coin if top_metric is not None else None),
            "top_wallet": best.wallet_address if best is not None else None,
            "carnets_analyzed": carnets,
            "l2_books_analyzed": carnets,
            "top_coins": top_coins,
            "coin_opportunities": top_coins,
            "wallets_positive_pnl_by_coin": positive_by_coin,
            "wallets_positive_pnl_altcoins": altcoin_positive,
        }

    def _autoscan_summary() -> dict[str, Any]:
        resolved_state = _resolved_autoscan_state()
        return {
            "running": state.discovery_running or state.autoscan_running,
            "started": state.autoscan_started,
            "current_step": state.autoscan_current_step,
            "progress_percent": state.autoscan_progress_percent,
            "last_state": resolved_state,
            "last_error": state.last_discovery_error,
            "analyzes": [
                {"group": "Marches", "items": ["meta", "allMids", "l2Book multi-coins", "liquidite", "spread"]},
                {"group": "Leaderboard", "items": ["lignes publiques", "adresses completes", "tronquees rejetees", "candidats"]},
                {"group": "Explorer", "items": ["transactions", "tx hashes", "adresses completes", "transaction tape", "revalidation"]},
                {"group": "Wallets", "items": ["watchlist", "scan queue", "fills", "positions", "deltas par coin"]},
                {"group": "Intelligence", "items": ["ouvertures", "fermetures", "profits", "patterns", "playbooks"]},
                {"group": "Paper/Risque", "items": ["follow signals", "risk gates", "paper simulation", "testnet locked"]},
            ],
        }

    def _resolved_autoscan_state() -> str:
        if state.autoscan_started and state.last_discovery_state == "idle" and not state.autoscan_running:
            return "completed_no_wallets"
        return state.last_discovery_state

    def _leaderboard_summary() -> dict[str, Any]:
        try:
            with session_factory() as session:
                run = session.scalar(select(LeaderboardRun).order_by(desc(LeaderboardRun.id)).limit(1))
                full = int(session.scalar(select(func.count()).select_from(LeaderboardWalletCandidate)) or 0)
                truncated = int(
                    session.scalar(
                        select(func.count())
                        .select_from(LeaderboardAddressValidation)
                        .where(LeaderboardAddressValidation.is_truncated.is_(True))
                    )
                    or 0
                )
        except SQLAlchemyError:
            run = None
            full = 0
            truncated = 0
        return {
            "leaderboard_read": run is not None,
            "rows_seen": run.rows_seen if run is not None else 0,
            "full_addresses_found": run.full_addresses_found if run is not None else full,
            "truncated_addresses_rejected": run.truncated_addresses_seen if run is not None else truncated,
            "candidates_created": run.candidates_created if run is not None else full,
            "status": run.status if run is not None else "IMPORT_REQUIRED",
        }

    def _explorer_summary() -> dict[str, Any]:
        try:
            with session_factory() as session:
                run = session.scalar(select(ExplorerRun).order_by(desc(ExplorerRun.id)).limit(1))
                transactions = int(session.scalar(select(func.count()).select_from(ExplorerTransaction)) or 0)
                tape = int(session.scalar(select(func.count()).select_from(ExplorerTransactionTape)) or 0)
                candidates = int(session.scalar(select(func.count()).select_from(ExplorerWalletCandidate)) or 0)
                rejected = int(
                    session.scalar(
                        select(func.count())
                        .select_from(ExplorerTransaction)
                        .where(ExplorerTransaction.validation_status != "FULL_ADDRESS_OK")
                    )
                    or 0
                )
        except SQLAlchemyError:
            run = None
            transactions = 0
            tape = 0
            candidates = 0
            rejected = 0
        return {
            "status": run.status if run is not None else "IMPORT_REQUIRED",
            "method": run.method if run is not None else None,
            "endpoints_found": run.endpoints_found if run is not None else 0,
            "events_seen": run.events_seen if run is not None else 0,
            "transactions_stored": transactions,
            "transaction_tape": tape,
            "full_addresses_found": run.full_addresses_found if run is not None else 0,
            "truncated_addresses_rejected": run.truncated_addresses_rejected if run is not None else rejected,
            "candidates_created": candidates,
            "error_message": run.error_message if run is not None else None,
            "next_action": "import_explorer_csv" if candidates == 0 else "revalidate_explorer_wallets",
        }

    def _intelligence_summary() -> dict[str, Any]:
        return {
            "openings_detected": safe_count(WalletOpening),
            "closings_detected": safe_count(WalletClosing),
            "patterns_ranked": safe_count(WalletOpeningPatternStats),
            "playbooks": safe_count(WalletPlaybook),
            "follow_signals": safe_count(FollowSignal),
            "paper_follow_orders": safe_count(PaperFollowOrder),
        }

    def _selected_wallets_by_coin() -> dict[str, int]:
        try:
            with session_factory() as session:
                rows = session.query(AutoWatchlist.coin, func.count(AutoWatchlist.id)).group_by(AutoWatchlist.coin).all()
        except SQLAlchemyError:
            return {}
        return {coin or "GLOBAL": int(count) for coin, count in rows}

    return router
