from __future__ import annotations

import json
import os
from hashlib import sha256
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from hl_observer import __version__
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.copying.runtime_v9_adapter import attach_v9_runtime_diagnostics
from hl_observer.data_sources.warehouse_coverage import build_warehouse_coverage_report
from hl_observer.opportunities.fresh_opportunity import FreshOpportunity, find_fresh_opportunities
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.signals.fill_admission import KIND_ENTRY, KIND_EXIT, FillAdmissionConfig, admit_live_fill, fill_identity
from hl_observer.simulation.decision_replay_analyzer import (
    LOGS_TO_SEND_DIRNAME,
    SUMMARY_CACHE_FILE,
    analyze_decision_logs_summary,
)
from hl_observer.simulation.live_filters import (
    DEFAULT_SIMULATION_ALLOW_ADD_AS_ENTRY,
    DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS,
    DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS,
    DEFAULT_SIMULATION_MIN_EDGE_BPS,
    DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE,
    DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS,
    calibrated_bool_env,
    calibrated_float_env,
    copy_candidate_signal_time_ms,
    delta_identity,
    hard_stale_signal_limit_ms,
    is_hard_stale_signal,
    should_skip_exotic_for_copy,
    should_skip_orphan_exit_or_unknown,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
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
from hl_observer.ui.persistent_state import (
    MAX_PERSISTED_LEDGER_EVENTS,
    persist_simulation_state,
    simulation_state_path,
)
from hl_observer.ui.safe_actions import run_safe_action
from hl_observer.ui.schemas import (
    UiActionRequest,
    UiLogLine,
    UiRiskGate,
    UiSignalRow,
    UiStatus,
    UiWalletRow,
)
from hl_observer.ui.simulation_log_export import export_simulation_diagnostics
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.wallets.delta_utils import (
    build_position_consensus,
    copy_delta_action,
    copy_delta_direction,
    delta_event_time_ms,
)


def create_router(settings: Settings, state: UiState, bus: UiEventBus) -> APIRouter:
    router = APIRouter()
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    template_path = Path(__file__).with_name("templates") / "index.html"
    simulation_overview_cache: dict[str, Any] = {"payload": None, "computed_at_ms": 0, "limit": None}

    def persist_simulation_state_safe(reason: str) -> Path | None:
        try:
            return persist_simulation_state(settings, state)
        except OSError as exc:
            state.add_event(
                "simulation_state_persist_unavailable",
                "Etat simulation non persiste: fichier runtime verrouille ou dossier non inscriptible.",
                payload={
                    "reason": reason,
                    "state_path": str(simulation_state_path(settings)),
                    "error": str(exc),
                },
            )
            return None

    def safe_count(model: type) -> int:
        try:
            with session_factory() as session:
                return int(session.scalar(select(func.count()).select_from(model)) or 0)
        except SQLAlchemyError:
            return 0

    def fast_table_count(session: Any, model: Any) -> int:
        """Fast UI counter for append-only runtime tables."""

        try:
            return int(session.scalar(select(func.max(model.id))) or 0)
        except SQLAlchemyError:
            return 0

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def safe_int_env(name: str) -> int | None:
        try:
            value = int(os.environ.get(name, ""))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def simulation_max_signal_age_ms() -> int:
        configured = safe_int_env("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS")
        # Keep the simulator selective without starving normal read-only latency.
        # Anything older than 2x this value is hard-skipped before scoring.
        return max(1_000, min(300_000, configured or DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS))

    def is_live_detected_delta_source(source: str | None) -> bool:
        normalized = str(source or "").lower()
        return any(
            token in normalized
            for token in (
                "hyperliquid_ws:userfills",
                "public_trades_ws",
                "publictradesws",
                "live",
                "stream",
                "websocket",
            )
        )

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
        if isinstance(raw_snapshot.get("prices"), dict):
            raw_snapshot = raw_snapshot["prices"]
        for coin, value in raw_snapshot.items():
            try:
                mids[str(coin).upper()] = float(value)
            except (TypeError, ValueError):
                continue
        return mids

    def latest_mark_prices_from_snapshots(snapshots: list[MarketSnapshot]) -> tuple[dict[str, float], dict[str, str]]:
        """Merge recent market snapshots, keeping the newest usable mark per coin.

        `publicTradesWS` snapshots are usually fresher but sparse. `allMids`
        snapshots are broader but may be older. Merging them avoids freezing an
        open paper position just because the latest snapshot only contains one
        traded coin.
        """

        prices: dict[str, float] = {}
        sources: dict[str, str] = {}
        ordered = sorted(
            snapshots,
            key=lambda row: (row.exchange_ts or 0, row.id or 0),
            reverse=True,
        )
        for snapshot in ordered:
            for coin, price in latest_mid_prices_from_snapshot(snapshot.raw_json).items():
                if coin in prices or price <= 0:
                    continue
                prices[coin] = price
                sources[coin] = snapshot.source or "market_snapshot"
        return prices, sources

    def simulation_delta_identity(row: PositionDeltaModel) -> str:
        return delta_identity(row)

    def build_consensus_replay_deltas(
        opportunities: list[FreshOpportunity],
        source_deltas: list[PositionDeltaModel],
        *,
        allow_add_as_entry: bool = False,
        processed_delta_keys: set[str] | None = None,
    ) -> list[PositionDeltaModel]:
        """Convert accepted fresh clusters into local replay-only entry deltas.

        The CLI opportunity engine works at cluster level, while the UI
        simulator replays PositionDeltaModel rows. This bridge keeps those two
        views consistent without creating or suggesting any real order.
        """

        synthetic_rows: list[PositionDeltaModel] = []
        for opportunity in opportunities:
            if opportunity.decision != "ACCEPT_LOCAL_SIMULATION":
                continue
            if opportunity.direction not in {"LONG", "SHORT"}:
                continue
            cluster_source_rows = [
                row
                for row in source_deltas
                if str(row.coin or "").upper() == opportunity.coin.upper()
                and copy_delta_direction(row, copy_delta_action(row)) == opportunity.direction
                and opportunity.first_seen_ms <= delta_event_time_ms(row) <= opportunity.last_seen_ms
            ]
            has_open_action = any(copy_delta_action(row) in {"OPEN_LONG", "OPEN_SHORT"} for row in cluster_source_rows)
            if not has_open_action and not allow_add_as_entry:
                continue
            cluster_source_delta_keys = [simulation_delta_identity(row) for row in cluster_source_rows]
            reference_price = safe_float(opportunity.leader_reference_price or opportunity.current_mid, 0.0)
            if reference_price <= 0:
                continue
            source_exchange_times = [int(row.exchange_ts or 0) for row in cluster_source_rows if int(row.exchange_ts or 0) > 0]
            source_detected_times = [int(row.detected_at_ms or 0) for row in cluster_source_rows if int(row.detected_at_ms or 0) > 0]
            wallet = (opportunity.wallets[0] if opportunity.wallets else "__consensus__").lower()
            notional = max(0.0, safe_float(opportunity.simulated_notional_usdt, 0.0))
            if notional <= 0:
                notional = max(0.0, min(50.0, safe_float(opportunity.total_notional_usdc, 0.0) / max(1, opportunity.wallet_count)))
            if notional <= 0:
                continue
            size = notional / reference_price
            signed_size = size if opportunity.direction == "LONG" else -size
            digest = sha256(
                (
                    f"{opportunity.coin}:{opportunity.direction}:{opportunity.first_seen_ms}:"
                    f"{opportunity.last_seen_ms}:{','.join(opportunity.wallets)}"
                ).encode("utf-8")
            ).hexdigest()[:48]
            synthetic_rows.append(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin=opportunity.coin,
                    previous_side="FLAT",
                    new_side=opportunity.direction,
                    previous_size=0.0,
                    current_size=signed_size,
                    new_size=signed_size,
                    delta_size=signed_size,
                    # Keep this at 0: the underlying real rows already carry
                    # the cluster notional used by consensus_snapshot().
                    delta_notional_usdc=0.0,
                    action="OPEN",
                    exchange_ts=max(0, opportunity.first_seen_ms - 1),
                    detected_at_ms=max(0, opportunity.first_seen_ms - 1),
                    source="fresh_opportunity_cluster_local_simulation",
                    side="B" if opportunity.direction == "LONG" else "A",
                    price=reference_price,
                    fill_size=abs(size),
                    delta_type="open_long" if opportunity.direction == "LONG" else "open_short",
                    confidence="high",
                    confidence_score=min(1.0, max(0.5, opportunity.opportunity_score / 100.0)),
                    is_paper_eligible=True,
                    delta_hash=f"op:{digest}",
                    raw_json={
                        "source": "fresh_opportunity_cluster",
                        "decision": opportunity.decision,
                        "wallet_count": opportunity.wallet_count,
                        "wallets": list(opportunity.wallets),
                        "edge_remaining_bps": opportunity.edge_remaining_bps,
                        "copy_degradation_bps": opportunity.copy_degradation_bps,
                        "simulated_notional_usdt": opportunity.simulated_notional_usdt,
                        "cluster_source_delta_keys": cluster_source_delta_keys,
                        "leader_exchange_ts": min(source_exchange_times) if source_exchange_times else None,
                        "leader_detected_ts": max(source_detected_times) if source_detected_times else opportunity.last_seen_ms,
                        "leader_signal_ts": opportunity.last_seen_ms,
                        "research_only": True,
                        "real_order_created": False,
                    },
                )
            )
        return synthetic_rows

    def build_bot_simulation(
        deltas: list[PositionDeltaModel],
        *,
        mid_prices: dict[str, float] | None = None,
        starting_equity_usdt: float = 1000.0,
        max_position_notional_usdt: float = 50.0,
        max_open_positions: int = 6,
        max_events: int = 2_000,
        now_timestamp_ms: int | None = None,
        existing_positions: dict[str, dict[str, Any]] | None = None,
        existing_events: list[dict[str, Any]] | None = None,
        processed_delta_keys: set[str] | None = None,
        existing_realized_pnl_usdc: float = 0.0,
        existing_entry_costs_paid_usdc: float = 0.0,
        existing_exit_costs_paid_usdc: float = 0.0,
        existing_reproduced_entries_total: int = 0,
        existing_reproduced_exits_total: int = 0,
    ) -> dict[str, Any]:
        """Simulate the bot's local no-money decisions from the incoming leader delta stream.

        This is intentionally a pessimistic local simulator: it follows only fresh
        leader deltas, applies costs, requires measurable edge, and never creates
        an order or a recommendation.
        """

        def encode_position_key(wallet: str, coin: str, direction: str) -> str:
            return f"{wallet.lower()}|{coin.upper()}|{direction.upper()}"

        def decode_position_key(value: str) -> tuple[str, str, str] | None:
            parts = value.split("|")
            if len(parts) != 3:
                return None
            return parts[0].lower(), parts[1].upper(), parts[2].upper()

        def csv_to_set(value: Any) -> set[str]:
            if not isinstance(value, str) or not value:
                return set()
            return {item.strip().lower() for item in value.split(",") if item.strip()}

        def set_to_csv(values: set[str]) -> str:
            return ",".join(sorted(value.lower() for value in values if value))

        def evidence_hash_for(event: dict[str, Any], *, position_key: tuple[str, str, str], replay_action: str) -> str:
            payload = {
                "delta_key": event.get("delta_key"),
                "wallet_address": event.get("wallet_address"),
                "coin": event.get("coin"),
                "leader_action": event.get("leader_action"),
                "leader_side": event.get("leader_side"),
                "observed_at_ms": event.get("observed_at_ms"),
                "matched_position_key": encode_position_key(*position_key),
                "bot_replay_action": replay_action,
                "leader_price": event.get("leader_price"),
                "edge_remaining_bps": event.get("edge_remaining_bps"),
                "copy_degradation_bps": event.get("copy_degradation_bps"),
                "copied_notional_usdt": event.get("copied_notional_usdt"),
                "paper_action_type": event.get("paper_action_type"),
            }
            raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
            return "ev:" + sha256(raw.encode("utf-8")).hexdigest()[:24]

        def paper_ref_for(*, replay_action: str, delta_key: str, position_key: tuple[str, str, str]) -> str:
            raw = f"{replay_action}|{delta_key}|{encode_position_key(*position_key)}"
            return "paper:" + sha256(raw.encode("utf-8")).hexdigest()[:20]

        def enrich_replay_evidence(event: dict[str, Any], *, position_key: tuple[str, str, str], replay_action: str) -> None:
            event["simulation_only"] = True
            event["read_only"] = True
            event["external_action"] = False
            event["execution"] = "forbidden"
            event["venue_endpoint"] = None
            event["secret_material_used"] = False
            event["raw_event_hash"] = str(event.get("delta_key") or "")
            event["paper_ref"] = paper_ref_for(
                replay_action=replay_action,
                delta_key=str(event.get("delta_key") or ""),
                position_key=position_key,
            )
            event["evidence_hash"] = evidence_hash_for(event, position_key=position_key, replay_action=replay_action)
            attach_v9_runtime_diagnostics(
                event,
                current_ms=current_ms,
                all_mids=mid_prices,
                run_id=f"ui-simulation:{current_ms}",
            )

        current_ms = now_timestamp_ms or now_ms()
        positions: dict[tuple[str, str, str], dict[str, Any]] = {}
        maintenance_events: list[dict[str, Any]] = []
        existing_processed_keys = set(processed_delta_keys or set())
        entry_replay_actions = {
            "PAPER_ENTRY_REPLAYED",
            "PAPER_ADD_REPLAYED",
            "PAPER_JOIN_ADD_AS_ENTRY",
            "PAPER_CONSENSUS_ENTRY_REPLAYED",
            "PAPER_CONSENSUS_ADD_ENTRY_REPLAYED",
            "PAPER_CONSENSUS_ADD_REPLAYED",
        }
        exit_replay_actions = {
            "PAPER_CLOSE_REPLAYED",
            "PAPER_REDUCE_REPLAYED",
            "PAPER_CONSENSUS_CLOSE_REPLAYED",
            "PAPER_CONSENSUS_REDUCE_REPLAYED",
        }
        accepted_entry_keys = {
            str(row.get("delta_key"))
            for row in (existing_events or [])
            if isinstance(row, dict)
            and row.get("status") == "LOCAL_REPLAY"
            and row.get("bot_replay_action") in entry_replay_actions
            and row.get("delta_key")
        }
        for raw_key, raw_position in (existing_positions or {}).items():
            decoded = decode_position_key(str(raw_key))
            if decoded is None or not isinstance(raw_position, dict):
                continue
            source_delta_key = str(raw_position.get("source_delta_key") or "")
            opened_at_ms = raw_position.get("opened_at_ms")
            if (
                not source_delta_key
                or (source_delta_key not in accepted_entry_keys and source_delta_key not in existing_processed_keys)
                or not opened_at_ms
            ):
                maintenance_events.append(
                    {
                        "delta_key": f"maintenance:drop_orphan:{raw_key}",
                        "wallet_address": raw_position.get("wallet_address") or decoded[0],
                        "coin": raw_position.get("coin") or decoded[1],
                        "leader_action": "MAINTENANCE",
                        "leader_side": raw_position.get("direction") or decoded[2],
                        "observed_at_ms": current_ms,
                        "bot_replay_action": "STATE_CLEANUP",
                        "status": "REFUSED",
                        "estimated_net_pnl_usdc": None,
                        "bot_position_size_after": 0,
                        "reason": "ORPHAN_VIRTUAL_POSITION_DROPPED_NO_ENTRY_LEDGER",
                        "research_only": True,
                        "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                        "simulation_only": True,
                        "read_only": True,
                        "external_action": False,
                        "execution": "forbidden",
                        "venue_endpoint": None,
                        "secret_material_used": False,
                    }
                )
                continue
            positions[decoded] = {
                "size": float(raw_position.get("size") or 0.0),
                "avg_price": float(raw_position.get("avg_price") or 0.0),
                "entry_costs": float(raw_position.get("entry_costs") or 0.0),
                "highest_price": float(raw_position.get("highest_price") or raw_position.get("avg_price") or 0.0),
                "lowest_price": float(raw_position.get("lowest_price") or raw_position.get("avg_price") or 0.0),
                "opened_at_ms": float(opened_at_ms or current_ms),
                "last_update_at_ms": float(raw_position.get("last_update_at_ms") or opened_at_ms or current_ms),
                "source_delta_key": source_delta_key,
                "position_mode": str(raw_position.get("position_mode") or "SINGLE_LEADER"),
                "leader_wallets_csv": str(raw_position.get("leader_wallets_csv") or decoded[0]),
                "closed_wallets_csv": str(raw_position.get("closed_wallets_csv") or ""),
                "seen_cluster_ids_csv": str(raw_position.get("seen_cluster_ids_csv") or ""),
                "last_cluster_id": str(raw_position.get("last_cluster_id") or ""),
                "last_replay_action": str(raw_position.get("last_replay_action") or ""),
                "last_evidence_hash": str(raw_position.get("last_evidence_hash") or ""),
                "last_paper_ref": str(raw_position.get("last_paper_ref") or ""),
                "last_v9_decision": str(raw_position.get("last_v9_decision") or ""),
                "last_v9_evidence_hash": str(raw_position.get("last_v9_evidence_hash") or ""),
                "last_v9_reasons": raw_position.get("last_v9_reasons") or [],
                "last_reduce_fraction": float(raw_position.get("last_reduce_fraction") or 0.0),
                "last_notional_closed_usdt": float(raw_position.get("last_notional_closed_usdt") or 0.0),
                "entry_count": int(raw_position.get("entry_count") or 0),
                "increase_count": int(raw_position.get("increase_count") or 0),
                "reduce_count": int(raw_position.get("reduce_count") or 0),
            }
        ledger_events: list[dict[str, Any]] = [
            dict(row)
            for row in (existing_events or [])[-MAX_PERSISTED_LEDGER_EVENTS:]
            if isinstance(row, dict)
        ]
        if maintenance_events:
            ledger_events.extend(maintenance_events)
        initial_ledger_length = len(ledger_events)
        processed_keys = set(existing_processed_keys)
        filter_diagnostics: Counter[str] = Counter()
        fresh_entry_diagnostics: Counter[str] = Counter()
        prefilter_skips: list[dict[str, Any]] = []
        # Coût round-trip réaliste Hyperliquid: ~4.5 bps taker + petit spread/slippage par côté.
        # 12 bps/côté (=24 round-trip) saignait artificiellement le PnL sur beaucoup de trades.
        # 6 bps/côté (=12 round-trip) est réaliste et honnête (pas de triche, juste pas exagéré).
        cost_bps = 6.0
        # LEVIER perp (réalisme Hyperliquid): la "mise" desired_notional est la MARGE bloquée,
        # et la position contrôle margin*leverage de notionnel. Le PnL = taille*Δprix porte donc
        # sur le notionnel LEVERAGÉ (un mouvement de 1% sur 100$ de marge à 5x = ~5$, pas 1$),
        # les frais aussi (sur le notionnel réel), et l'exposition/cash reste comptée en MARGE
        # (les plafonds protègent toujours les 1000$). Defaut 5x ; HYPERSMART_SIMULATION_LEVERAGE.
        simulation_leverage = max(1.0, calibrated_float_env("HYPERSMART_SIMULATION_LEVERAGE", 5.0))
        min_edge_required_bps = max(
            1.0,
            calibrated_float_env("HYPERSMART_SIMULATION_MIN_EDGE_BPS", DEFAULT_SIMULATION_MIN_EDGE_BPS),
        )
        max_signal_age_ms = simulation_max_signal_age_ms()
        consensus_window_ms = min(4_000, max_signal_age_ms)
        realtime_score_config = RealtimeCopyRiskConfig(
            min_edge_required_bps=min_edge_required_bps,
            fee_bps=4.0,
            spread_bps=3.0,
            slippage_bps=5.0,
            max_signal_age_ms=max_signal_age_ms,
            min_liquidity_score=calibrated_float_env(
                "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE",
                DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE,
            ),
            max_copy_degradation_bps=calibrated_float_env(
                "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS",
                DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS,
            ),
            max_price_deviation_bps=calibrated_float_env("HYPERSMART_SIMULATION_MAX_PRICE_DEVIATION_BPS", 8.0),
            starting_equity_usdt=starting_equity_usdt,
            max_position_notional_usdt=max_position_notional_usdt,
            max_total_exposure_usdt=max_position_notional_usdt * 8.0,
            single_wallet_min_edge_required_bps=calibrated_float_env(
                "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS",
                DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS,
            ),
        )
        v9_pipeline_authoritative = str(os.environ.get("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "0")).lower() in {"1", "true", "yes"}

        chronological = sorted(deltas, key=delta_event_time_ms)
        entry_rows_by_coin_direction: dict[tuple[str, str], list[PositionDeltaModel]] = defaultdict(list)
        for indexed_row in chronological:
            indexed_action = copy_delta_action(indexed_row)
            indexed_direction = copy_delta_direction(indexed_row, indexed_action)
            if indexed_direction in {"LONG", "SHORT"} and indexed_action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
                entry_rows_by_coin_direction[(indexed_row.coin.upper(), indexed_direction)].append(indexed_row)

        def copy_signal_time_ms(row: PositionDeltaModel) -> int:
            return copy_candidate_signal_time_ms(row)

        def record_prefilter_skip(
            row: PositionDeltaModel,
            *,
            reason: str,
            action: str | None = None,
            direction: str | None = None,
            signal_time_ms: int | None = None,
            detail: str | None = None,
        ) -> None:
            if len(prefilter_skips) >= 200:
                return
            signal_time = int(signal_time_ms or copy_signal_time_ms(row) or 0)
            exchange_time = int(row.exchange_ts or 0)
            detected_time = int(row.detected_at_ms or 0)
            prefilter_skips.append(
                {
                    "delta_key": simulation_delta_identity(row),
                    "wallet_address": row.wallet_address,
                    "coin": row.coin,
                    "leader_action": action or copy_delta_action(row),
                    "leader_side": direction or copy_delta_direction(row, action or copy_delta_action(row)),
                    "reason": reason,
                    "detail": detail or "",
                    "source": row.source,
                    "exchange_ts": exchange_time or None,
                    "detected_at_ms": detected_time or None,
                    "signal_time_ms": signal_time or None,
                    "signal_age_ms": max(0, current_ms - signal_time) if signal_time > 0 else None,
                    "max_signal_age_ms": max_signal_age_ms,
                    "hard_stale_limit_ms": hard_stale_signal_limit_ms(max_signal_age_ms),
                    "price": row.price,
                    "delta_notional_usdc": row.delta_notional_usdc,
                    "research_only": True,
                    "execution": "forbidden",
                }
            )

        def current_open_exposure_usdt() -> float:
            # Exposure measured in MARGIN (capital deployed): position["size"] is the LEVERAGED
            # coin quantity, so divide the leveraged notional back by the leverage to get margin.
            return sum(abs(position["size"] * position["avg_price"]) for position in positions.values()) / simulation_leverage

        def new_realized_net_pnl_so_far() -> float:
            return sum(
                float(row.get("estimated_net_pnl_usdc") or 0.0)
                for row in ledger_events[initial_ledger_length:]
                if row.get("status") == "LOCAL_REPLAY"
            )

        def simulated_equity_so_far() -> float:
            return starting_equity_usdt + float(existing_realized_pnl_usdc or 0.0) + new_realized_net_pnl_so_far()

        coin_loss_cooldown_usdc = max(0.35, starting_equity_usdt * 0.0005)
        leader_loss_cooldown_usdc = max(0.25, starting_equity_usdt * 0.00035)

        def session_pnl_for(*, coin: str | None = None, wallet: str | None = None) -> float:
            pnl = 0.0
            wallet_lower = wallet.lower() if wallet else None
            coin_upper = coin.upper() if coin else None
            for item in ledger_events:
                if item.get("status") != "LOCAL_REPLAY":
                    continue
                if coin_upper and str(item.get("coin") or "").upper() != coin_upper:
                    continue
                if wallet_lower and str(item.get("wallet_address") or "").lower() != wallet_lower:
                    continue
                try:
                    pnl += float(item.get("estimated_net_pnl_usdc") or 0.0)
                except (TypeError, ValueError):
                    continue
            return pnl

        def adaptive_session_risk_reason(row: PositionDeltaModel, metrics: dict[str, float | int | str]) -> str | None:
            coin_pnl = session_pnl_for(coin=row.coin)
            wallet_pnl = session_pnl_for(wallet=row.wallet_address)
            consensus_wallets = int(metrics.get("consensus_wallets") or 0)
            edge_remaining_bps = safe_float(metrics.get("edge_remaining_bps"), -9999.0)
            min_edge = safe_float(getattr(realtime_score_config, "min_edge_required_bps", min_edge_required_bps), min_edge_required_bps)
            strong_recovery_edge_bps = min_edge + (10.0 if consensus_wallets >= 3 else 18.0)
            severe_coin_loss = coin_pnl <= -(coin_loss_cooldown_usdc * 4.0)
            severe_leader_loss = wallet_pnl <= -(leader_loss_cooldown_usdc * 4.0)
            if severe_coin_loss:
                return "COIN_SESSION_LOSS_COOLDOWN"
            if severe_leader_loss:
                return "LEADER_SESSION_LOSS_COOLDOWN"
            if coin_pnl <= -coin_loss_cooldown_usdc and edge_remaining_bps < strong_recovery_edge_bps:
                return "COIN_SESSION_LOSS_REQUIRES_STRONGER_EDGE"
            if wallet_pnl <= -leader_loss_cooldown_usdc and edge_remaining_bps < strong_recovery_edge_bps:
                return "LEADER_SESSION_LOSS_REQUIRES_STRONGER_EDGE"
            return None

        def consensus_snapshot(row: PositionDeltaModel, direction: str) -> dict[str, Any]:
            observed_at = delta_event_time_ms(row)
            if observed_at <= 0:
                wallet = row.wallet_address.lower()
                return {
                    "wallet_count": 1,
                    "wallets": {wallet},
                    "wallets_csv": wallet,
                    "first_seen_ms": 0,
                    "last_seen_ms": 0,
                    "total_notional_usdc": abs(safe_float(row.delta_notional_usdc, 0.0)),
                    "median_reference_price": safe_float(row.price, 0.0),
                    "cluster_id": f"{row.coin.upper()}:{direction}:unknown",
                }
            start_at = observed_at - consensus_window_ms
            end_at = observed_at + consensus_window_ms
            candidates = entry_rows_by_coin_direction.get((row.coin.upper(), direction), [])
            matched_rows = [
                item
                for item in candidates
                if start_at <= delta_event_time_ms(item) <= end_at
            ]
            wallets = {
                item.wallet_address.lower()
                for item in matched_rows
            }
            if not wallets:
                wallets = {row.wallet_address.lower()}
                matched_rows = [row]
            first_seen = min((delta_event_time_ms(item) for item in matched_rows), default=observed_at)
            last_seen = max((delta_event_time_ms(item) for item in matched_rows), default=observed_at)
            notionals = [abs(safe_float(item.delta_notional_usdc, 0.0)) for item in matched_rows]
            prices = sorted(safe_float(item.price, 0.0) for item in matched_rows if safe_float(item.price, 0.0) > 0)
            median_price = prices[len(prices) // 2] if prices else safe_float(row.price, 0.0)
            return {
                "wallet_count": max(1, len(wallets)),
                "wallets": wallets,
                "wallets_csv": set_to_csv(wallets),
                "first_seen_ms": first_seen,
                "last_seen_ms": last_seen,
                "total_notional_usdc": round(sum(notionals), 6),
                "median_reference_price": round(median_price, 8),
                "cluster_id": f"{row.coin.upper()}:{direction}:{first_seen}",
            }

        def consensus_wallet_count(row: PositionDeltaModel, direction: str) -> int:
            return int(consensus_snapshot(row, direction)["wallet_count"])

        def position_key_for_row(
            row: PositionDeltaModel,
            direction: str,
            action: str,
            metrics: dict[str, float | int | str] | None = None,
        ) -> tuple[str, str, str]:
            wallet_key = (row.wallet_address.lower(), row.coin.upper(), direction)
            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
                if int((metrics or {}).get("consensus_wallets") or 0) >= 2:
                    return ("__consensus__", row.coin.upper(), direction)
                return wallet_key
            if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
                if wallet_key in positions:
                    return wallet_key
                consensus_key = ("__consensus__", row.coin.upper(), direction)
                previous = positions.get(consensus_key)
                if previous is not None:
                    leader_wallets = csv_to_set(previous.get("leader_wallets_csv"))
                    if not leader_wallets or row.wallet_address.lower() in leader_wallets:
                        return consensus_key
            return wallet_key

        def opportunity_metrics(row: PositionDeltaModel, direction: str) -> dict[str, float | int | str]:
            observed_at = delta_event_time_ms(row)
            leader_event_at = copy_signal_time_ms(row)
            exchange_at = int(row.exchange_ts or 0)
            detected_at = int(row.detected_at_ms or 0)
            raw_json = row.raw_json if isinstance(row.raw_json, dict) else {}
            if row.source == "fresh_opportunity_cluster_local_simulation":
                exchange_at = int(raw_json.get("leader_exchange_ts") or exchange_at or 0)
                detected_at = int(raw_json.get("leader_detected_ts") or detected_at or 0)
                leader_event_at = int(raw_json.get("leader_signal_ts") or detected_at or leader_event_at or 0)
            age_ms = max(0, current_ms - leader_event_at) if leader_event_at > 0 else max_signal_age_ms
            consensus = consensus_snapshot(row, direction)
            consensus_count = int(consensus["wallet_count"])
            confidence = max(0.0, min(1.0, float(row.confidence_score or 0.5)))
            leader_expected_edge_bps = 18.0 + confidence * 34.0 + min(24.0, (consensus_count - 1) * 8.0)
            leader_size = abs(float(row.delta_size or row.fill_size or 0.0))
            leader_notional = abs(float(row.delta_notional_usdc or (leader_size * float(row.price or 0.0))))
            cluster_notional = max(leader_notional, safe_float(consensus.get("total_notional_usdc"), 0.0))
            # For consensus entries, the useful liquidity evidence is the whole
            # same-coin/same-side burst, not only the tiny fill currently being
            # iterated. Without this, a valid 3-wallet cluster made of small
            # fills was rejected as low liquidity even when the cluster notional
            # was large enough for a 1000 USDT virtual portfolio.
            liquidity_basis = cluster_notional if consensus_count >= 2 else leader_notional
            liquidity_score = max(0.2, min(1.0, liquidity_basis / 2_500.0))
            current_mid = (mid_prices or {}).get(str(row.coin).upper())
            leader_reference_price = safe_float(consensus.get("median_reference_price"), float(row.price or 0.0))
            score = score_realtime_copy_candidate(
                RealtimeCopyScoreInput(
                    action_type=copy_delta_action(row),
                    direction=direction,
                    leader_expected_edge_bps=leader_expected_edge_bps,
                    leader_consistency_factor=0.72 + confidence * 0.28,
                    signal_age_ms=age_ms,
                    consensus_wallets=consensus_count,
                    liquidity_score=liquidity_score,
                    leader_score=confidence * 100.0,
                    leader_reference_price=leader_reference_price,
                    current_mid=current_mid,
                    leader_notional_usdt=cluster_notional / max(1, consensus_count),
                    current_open_exposure_usdt=current_open_exposure_usdt(),
                    current_open_positions=len(positions),
                    max_open_positions=max_open_positions,
                ),
                config=realtime_score_config,
            )
            decision_reason = (
                "EDGE_OK_FOR_LOCAL_SIMULATION"
                if score.accepted
                else "|".join(score.refusal_reasons or ["REJECT_NO_TRADE"])
            )
            # V12 unified gate (SHADOW only — never changes the real decision above).
            try:
                from hl_observer.signals.copy_decision import (
                    CopyInputs as _V12In,
                    evaluate_copy_candidate as _v12_eval,
                )
                _v12 = _v12_eval(_V12In(
                    source_usable=True,
                    quotes_agree=True,
                    mid_available=current_mid is not None,
                    signal_age_ms=int(age_ms) if age_ms is not None else None,
                    max_signal_age_ms=int(getattr(realtime_score_config, "max_signal_age_ms", 30000) or 30000),
                    liquidity_score=float(liquidity_score) if liquidity_score is not None else None,
                    min_liquidity_score=float(getattr(realtime_score_config, "min_liquidity_score", 0.0) or 0.0),
                    spread_bps=float(getattr(realtime_score_config, "spread_bps", 0.0) or 0.0),
                    max_spread_bps=20.0,
                    net_edge_bps=float(score.edge_remaining_bps) if score.edge_remaining_bps is not None else None,
                    min_edge_bps=float(getattr(realtime_score_config, "min_edge_required_bps", 0.0) or 0.0),
                ))
                _v12_accepted, _v12_reason = _v12.accepted, _v12.reason_code
            except Exception:
                _v12_accepted, _v12_reason = None, None
            # V12 promotion (opt-in): when HYPERSMART_V12_GATE_AUTHORITATIVE=1, the unified
            # gate becomes BINDING as a stricter intersection — a candidate survives only if
            # BOTH the realtime score AND the unified gate accept. This can only *reduce*
            # trades (cleaner), never open new ones. Default OFF => pure shadow (unchanged
            # behavior), so the engine can never be broken by flipping this on.
            try:
                from hl_observer.signals.gate_promotion import merge_authoritative_decision as _v12_promote
                decision_reason = _v12_promote(
                    score_reason=decision_reason,
                    v12_accepted=_v12_accepted,
                    v12_reason=_v12_reason,
                    authoritative=calibrated_bool_env("HYPERSMART_V12_GATE_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            # V13 shadow wiring: dormant quant modules (whale-fill / vol-regime / ranker /
            # streak-sizing / multi-TF bias) computed in SHADOW — exposed for the dashboard
            # and ledger, NEVER decides alone (context_only). Guarded: any failure -> {} so
            # the engine is never broken. Promotion to authoritative is a later explicit step.
            try:
                from hl_observer.signals.shadow_wiring import compute_shadow_signals as _v13_shadow
                _v13 = _v13_shadow(
                    action_type=copy_delta_action(row),
                    coin=str(row.coin),
                    side=direction,
                    age_ms=int(age_ms) if age_ms is not None else 0,
                    consensus_wallets=consensus_count,
                    leader_score=confidence * 100.0,
                    leader_notional_usdc=cluster_notional,
                    net_edge_bps=float(getattr(score, "edge_remaining_bps", 0.0) or 0.0),
                    liquidity_score=float(getattr(score, "liquidity_score", liquidity_score) or 0.0),
                    adverse_move_bps=float(getattr(score, "adverse_price_move_bps", 0.0) or 0.0),
                    price_deviation_bps=float(getattr(score, "price_deviation_bps", 0.0) or 0.0),
                    confidence=confidence,
                )
            except Exception:
                _v13 = {}
            # V13 model promotion (opt-in): when HYPERSMART_V13_MODEL_AUTHORITATIVE=1 the local
            # model becomes binding as a stricter intersection — it can only turn an accepting
            # score into REJECT_MODEL_LOW_P, never create a trade. Default OFF => pure shadow.
            try:
                from hl_observer.ml.inference import apply_model_promotion as _v13_model_promote
                decision_reason = _v13_model_promote(
                    score_reason=decision_reason,
                    model_accept=_v13.get("shadow_model_accept"),
                    authoritative=calibrated_bool_env("HYPERSMART_V13_MODEL_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            # V14 #168 — promote the whale-fill to a PRIMARY entry source (opt-in). When
            # HYPERSMART_V14_WHALE_PRIMARY_AUTHORITATIVE=1 a candidate the score accepts is
            # REJECTED unless a primary whale fill backs it (shadow_whale_primary). Stricter
            # intersection: can only reduce trades. None (signal unknown) never blocks. OFF default.
            try:
                from hl_observer.signals.whale_primary_gate import apply_whale_primary_promotion as _v14_whale_promote
                decision_reason = _v14_whale_promote(
                    score_reason=decision_reason,
                    whale_primary=_v13.get("shadow_whale_primary"),
                    authoritative=calibrated_bool_env("HYPERSMART_V14_WHALE_PRIMARY_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            # V14 #170 — warmup guard (opt-in): block entries until HTF bars/features are ready.
            # warmup_ready is unknown in this scope (bars context not plumbed into the hot path
            # yet) -> None -> no-op (safe). When wired, set HYPERSMART_V14_WARMUP_AUTHORITATIVE=1
            # to make it binding. Stricter intersection: only reduces trades.
            try:
                from hl_observer.signals.warmup_guard import apply_warmup_promotion as _v14_warmup_promote
                decision_reason = _v14_warmup_promote(
                    score_reason=decision_reason,
                    warmup_ready=None,
                    authoritative=calibrated_bool_env("HYPERSMART_V14_WARMUP_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            # V14 #175 — hot consensus window (≈4 s hot / 15 s max): veto entries whose signal
            # is already outside the fresh window. Functional from the measured signal age.
            # Stricter intersection: can only reduce trades. None age never blocks. OFF default.
            try:
                from hl_observer.signals.consensus_window import (
                    consensus_window_status as _v14_cw_status,
                    apply_consensus_window_promotion as _v14_cw_promote,
                )
                _cw_in_window = None
                if age_ms is not None:
                    _cw_in_window = _v14_cw_status(first_seen_ms=0, now_ms=int(age_ms)).in_window
                decision_reason = _v14_cw_promote(
                    score_reason=decision_reason,
                    in_window=_cw_in_window,
                    authoritative=calibrated_bool_env("HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            # V14 #182/#183/#167 — exec-cost net-edge + entry-quality (smart-money + depth) +
            # liquidation shadow, computed from REAL in-scope signals (edge_remaining, liquidity,
            # notional, leader score). All flags OFF by default => shadow. Gates only reduce trades.
            _v14b: dict = {}
            try:
                from hl_observer.copy_fidelity.exec_cost_model import model_exec_costs, net_edge_after_costs
                from hl_observer.copy_fidelity.slippage_model import slippage_bps as _v14_slip
                from hl_observer.copy_fidelity.exec_cost_promotion import apply_exec_cost_promotion as _v14_exec_promote
                _gross_edge = float(getattr(score, "edge_remaining_bps", 0.0) or 0.0)
                _notional = float(getattr(score, "simulated_notional_usdt", 0.0) or 0.0)
                # slippage from REAL notional + REAL liquidity; fee = HL taker base; half-spread =
                # conservative constant (per-coin L2 spread not in this closure yet).
                _slip = _v14_slip(notional_usd=_notional, liquidity_score=float(liquidity_score))
                _costs = model_exec_costs(fee_bps=4.5, half_spread_bps=1.5, slippage_bps=_slip, latency_bps=0.0, is_maker=False)
                _net_after_exec = net_edge_after_costs(gross_edge_bps=_gross_edge, costs=_costs)
                _v14b["shadow_exec_cost_bps"] = _costs.total_cost_bps
                _v14b["shadow_net_edge_after_exec_bps"] = _net_after_exec
                decision_reason = _v14_exec_promote(
                    score_reason=decision_reason,
                    net_edge_bps=_net_after_exec,
                    min_net_edge_bps=calibrated_float_env("HYPERSMART_V14_EXEC_MIN_NET_EDGE_BPS", 0.0),
                    authoritative=calibrated_bool_env("HYPERSMART_V14_EXEC_COST_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            try:
                from hl_observer.signals.entry_quality_gate import apply_entry_quality_promotion as _v14_eq_promote
                _min_liq = float(getattr(realtime_score_config, "min_liquidity_score", 0.0) or 0.0)
                _depth_ok = (float(liquidity_score) >= _min_liq) if _min_liq > 0 else None
                _sm_ok = (float(confidence) * 100.0) >= calibrated_float_env("HYPERSMART_V14_SMART_MONEY_MIN_SCORE", 60.0)
                _v14b["shadow_entry_quality_depth_ok"] = _depth_ok
                _v14b["shadow_entry_quality_smart_money_ok"] = bool(_sm_ok)
                decision_reason = _v14_eq_promote(
                    score_reason=decision_reason,
                    smart_money_ok=_sm_ok,
                    depth_ok=_depth_ok,
                    authoritative=calibrated_bool_env("HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE", False),
                )
            except Exception:
                pass
            try:
                _liq = (raw_json.get("liquidation") or raw_json.get("liq")) if isinstance(raw_json, dict) else None
                _v14b["shadow_liquidation_present"] = (bool(_liq) if _liq is not None else None)
            except Exception:
                _v14b["shadow_liquidation_present"] = None
            return {
                **_v13,
                **_v14b,
                "signal_age_ms": age_ms,
                "v12_gate_accepted": _v12_accepted,
                "v12_gate_reason": _v12_reason,
                "leader_exchange_ts": exchange_at or None,
                "leader_detected_ts": detected_at or None,
                "leader_signal_ts": leader_event_at or None,
                "cluster_notional_usdc": round(cluster_notional, 6),
                "leader_reference_price": round(leader_reference_price, 8),
                "signal_freshness_score": score.signal_freshness_score,
                "consensus_wallets": score.consensus_wallets,
                "consensus_wallets_csv": str(consensus["wallets_csv"]),
                "consensus_cluster_id": str(consensus["cluster_id"]),
                "consensus_first_seen_ms": int(consensus["first_seen_ms"] or 0),
                "consensus_last_seen_ms": int(consensus["last_seen_ms"] or 0),
                "position_mode": "CONSENSUS_CLUSTER" if consensus_count >= 2 else "SINGLE_LEADER",
                "leader_expected_edge_bps": score.leader_expected_edge_bps or 0.0,
                "leader_consistency_factor": score.leader_consistency_factor,
                "consensus_factor": score.consensus_factor,
                "liquidity_score": score.liquidity_score,
                "leader_score": score.leader_score,
                "copy_degradation_bps": score.copy_degradation_bps,
                "edge_remaining_bps": score.edge_remaining_bps,
                "opportunity_score": score.opportunity_score,
                "risk_score": score.risk_score,
                "price_deviation_bps": score.price_deviation_bps,
                "adverse_price_move_bps": score.adverse_price_move_bps,
                "simulated_notional_usdt": score.simulated_notional_usdt,
                "decision_reason": decision_reason,
            }

        allow_add_as_entry = calibrated_bool_env(
            "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY",
            DEFAULT_SIMULATION_ALLOW_ADD_AS_ENTRY,
        )
        fill_admission_config = FillAdmissionConfig(
            max_signal_age_ms=max_signal_age_ms,
            hard_backfill_age_ms=max_signal_age_ms * 2,
            allow_add_as_entry=allow_add_as_entry,
            allow_exotic_markets=bool(settings.market_universe.include_builder_and_rwa_perps),
            future_tolerance_ms=max(15_000, max_signal_age_ms),
        )

        for row in chronological:
            current_delta_key = simulation_delta_identity(row)
            if current_delta_key in processed_keys:
                filter_diagnostics["duplicate_delta_skipped"] += 1
                continue
            processed_keys.add(current_delta_key)

            if should_skip_exotic_for_copy(
                row.coin,
                include_builder_and_rwa_perps=bool(settings.market_universe.include_builder_and_rwa_perps),
            ):
                filter_diagnostics["exotic_market_skipped"] += 1
                record_prefilter_skip(row, reason="EXOTIC_MARKET_SKIPPED", detail="coin excluded from copy simulation universe")
                continue

            action = copy_delta_action(row)
            direction = copy_delta_direction(row, action)
            signal_time_ms = copy_signal_time_ms(row)
            admission_position_key = (
                position_key_for_row(row, direction, action, None)
                if direction is not None and action != "UNKNOWN"
                else None
            )
            admission_has_position = (
                admission_position_key is not None
                and admission_position_key in positions
                and float(positions[admission_position_key].get("size") or 0.0) > 0
            )
            admission_key = fill_identity(
                wallet_address=str(row.wallet_address or ""),
                coin=str(row.coin or ""),
                side=str(direction or ""),
                action_type=action,
                price=safe_float(row.price, 0.0),
                size=abs(safe_float(row.delta_size, 0.0) or safe_float(row.fill_size, 0.0)),
                ts_ms=signal_time_ms,
            )
            admission = admit_live_fill(
                action_type=action,
                coin=str(row.coin or ""),
                fill_ts_ms=signal_time_ms,
                now_ms=current_ms,
                already_seen=admission_key in processed_keys,
                has_matching_paper_position=admission_has_position,
                leader_price=safe_float(row.price, 0.0),
                config=fill_admission_config,
            )
            fresh_entry_diagnostics["admission_candidates_seen"] += 1
            if admission.kind == KIND_ENTRY:
                fresh_entry_diagnostics["admission_entries_seen"] += 1
                if admission.is_fresh:
                    fresh_entry_diagnostics["admission_fresh_entries_seen"] += 1
            elif admission.kind == KIND_EXIT:
                fresh_entry_diagnostics["admission_exits_seen"] += 1
            if not admission.admit:
                filter_diagnostics[f"admission_{admission.reason.lower()}"] += 1
                if admission.reason == "STALE_BACKFILL":
                    filter_diagnostics["hard_stale_entry_skipped"] += 1
                    fresh_entry_diagnostics["entry_candidates_hard_stale"] += 1
                elif admission.reason == "NO_PAPER_POSITION_FOR_EXIT":
                    filter_diagnostics["orphan_exit_skipped"] += 1
                elif admission.reason == "DUPLICATE_FILL":
                    filter_diagnostics["duplicate_delta_skipped"] += 1
                elif admission.reason == "EXOTIC_MARKET":
                    filter_diagnostics["exotic_market_skipped"] += 1
                elif admission.reason == "UNKNOWN_DELTA":
                    filter_diagnostics["unknown_delta_skipped"] += 1
                record_prefilter_skip(
                    row,
                    reason=(
                        "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
                        if admission.reason == "NO_PAPER_POSITION_FOR_EXIT"
                        else admission.reason
                    ),
                    action=action,
                    direction=direction,
                    signal_time_ms=signal_time_ms,
                    detail=f"fill admission rejected before ledger; kind={admission.kind}",
                )
                continue
            processed_keys.add(admission_key)
            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
                fresh_entry_diagnostics["entry_candidates_seen"] += 1
                if is_hard_stale_signal(
                    signal_time_ms=signal_time_ms,
                    now_ms=current_ms,
                    max_signal_age_ms=max_signal_age_ms,
                ):
                    filter_diagnostics["hard_stale_entry_skipped"] += 1
                    fresh_entry_diagnostics["entry_candidates_hard_stale"] += 1
                    record_prefilter_skip(
                        row,
                        reason="HARD_STALE_ENTRY",
                        action=action,
                        direction=direction,
                        signal_time_ms=signal_time_ms,
                        detail="entry was detected but older than the hard stale copy window",
                    )
                    continue
                fresh_entry_diagnostics["entry_candidates_scored"] += 1

            _coin_up = row.coin.upper() if row.coin else ""
            if _coin_up and (_coin_up in (settings.market_universe.excluded_coins or [])
                             or any(_mk in _coin_up for _mk in (":", "@", "#"))):
                event = {
                    "delta_key": current_delta_key,
                    "wallet_address": row.wallet_address,
                    "coin": row.coin,
                    "leader_action": action,
                    "leader_side": direction,
                    "observed_at_ms": delta_event_time_ms(row),
                    "bot_replay_action": "NO_TRADE",
                    "status": "REFUSED",
                    "reason": ("EXOTIC_MARKET_SKIPPED" if any(_mk in _coin_up for _mk in (":", "@", "#")) else "COIN_BLACKLISTED"),
                    "research_only": True,
                    "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                    "simulation_only": True,
                    "read_only": True,
                    "external_action": False,
                    "execution": "forbidden",
                    "venue_endpoint": None,
                    "secret_material_used": False,
                }
                ledger_events.append(event)
                continue

            event: dict[str, Any] = {
                "delta_key": current_delta_key,
                "wallet_address": row.wallet_address,
                "coin": row.coin,
                "leader_action": action,
                "leader_side": direction,
                "observed_at_ms": delta_event_time_ms(row),
                "leader_price": row.price,
                "leader_delta_size": row.delta_size,
                "leader_notional_usdc": row.delta_notional_usdc,
                "bot_replay_action": "NO_TRADE",
                "status": "REFUSED",
                "estimated_net_pnl_usdc": None,
                "bot_position_size_after": None,
                "reason": None,
                "research_only": True,
                "paper_mode": "PAPER_LOCAL_USDT_ONLY",
                "simulation_only": True,
                "read_only": True,
                "external_action": False,
                "execution": "forbidden",
                "venue_endpoint": None,
                "secret_material_used": False,
            }
            if action == "UNKNOWN" or direction is None:
                filter_diagnostics["unknown_delta_skipped"] += 1
                record_prefilter_skip(
                    row,
                    reason="UNKNOWN_DELTA",
                    action=action,
                    direction=direction,
                    signal_time_ms=signal_time_ms,
                    detail="delta direction/action could not be classified safely",
                )
                continue
            if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
                preliminary_key = position_key_for_row(row, direction, action, None)
                previous_position = positions.get(preliminary_key)
                if should_skip_orphan_exit_or_unknown(action, previous_position is not None and previous_position["size"] > 0):
                    filter_diagnostics["orphan_exit_skipped"] += 1
                    record_prefilter_skip(
                        row,
                        reason="NO_MATCHING_PAPER_POSITION_FOR_CLOSE",
                        action=action,
                        direction=direction,
                        signal_time_ms=signal_time_ms,
                        detail="leader exit/reduce seen but no matching local virtual position exists",
                    )
                    continue
            if row.price is None or row.price <= 0:
                event["reason"] = "PRICE_MISSING"
                ledger_events.append(event)
                continue

            metrics = opportunity_metrics(row, direction)
            key = position_key_for_row(row, direction, action, metrics)
            event.update(metrics)
            if event.get("edge_remaining_bps") is None and action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
                event["edge_remaining_bps"] = 0.0
                event["edge_context"] = "EXIT_SIGNAL_FOLLOWS_LEADER_POSITION_NOT_ENTRY_EDGE_GATE"
            event["matched_position_key"] = encode_position_key(*key)
            signal_age_value = metrics.get("signal_age_ms")
            leader_size = abs(float(row.delta_size or row.fill_size or 0.0))
            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"} and metrics["decision_reason"] != "EDGE_OK_FOR_LOCAL_SIMULATION":
                event["reason"] = str(metrics["decision_reason"])
                ledger_events.append(event)
                continue

            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
                adaptive_risk_reason = adaptive_session_risk_reason(row, metrics)
                if adaptive_risk_reason:
                    event["reason"] = adaptive_risk_reason
                    event["coin_session_pnl_usdc"] = round(session_pnl_for(coin=row.coin), 6)
                    event["leader_session_pnl_usdc"] = round(session_pnl_for(wallet=row.wallet_address), 6)
                    ledger_events.append(event)
                    continue
                desired_notional = float(metrics.get("simulated_notional_usdt") or 0.0)
                if desired_notional <= 0:
                    event["reason"] = "MAX_EXPOSURE_REACHED"
                    ledger_events.append(event)
                    continue
                try:
                    from hl_observer.simulation.adaptive_paper_sizing import adaptive_paper_margin

                    adaptive_size = adaptive_paper_margin(
                        requested_margin_usdt=desired_notional,
                        equity_usdt=simulated_equity_so_far(),
                        recent_events=ledger_events,
                        edge_remaining_bps=safe_float(metrics.get("edge_remaining_bps"), 0.0),
                        liquidity_score=safe_float(metrics.get("liquidity_score"), 0.0),
                        consensus_wallets=int(metrics.get("consensus_wallets") or 0),
                        min_margin_usdt=realtime_score_config.min_position_notional_usdt,
                        max_margin_usdt=realtime_score_config.max_position_notional_usdt,
                        enabled=calibrated_bool_env("HYPERSMART_ADAPTIVE_PAPER_SIZING", True),
                    )
                    event.update(adaptive_size.to_log_fields())
                    if adaptive_size.final_margin_usdt <= 0:
                        event["reason"] = adaptive_size.reason
                        ledger_events.append(event)
                        continue
                    desired_notional = adaptive_size.final_margin_usdt
                except Exception as exc:
                    event["adaptive_sizing_error"] = f"{exc.__class__.__name__}: {exc}"
                free_cash_before_entry = max(0.0, simulated_equity_so_far() - current_open_exposure_usdt())
                if desired_notional > free_cash_before_entry:
                    event["reason"] = "INSUFFICIENT_SIMULATED_USDT"
                    event["available_simulated_usdt"] = round(free_cash_before_entry, 6)
                    event["requested_notional_usdt"] = round(desired_notional, 6)
                    ledger_events.append(event)
                    continue
                # PERP LEVERAGE: desired_notional is the MARGIN (stake); the position controls
                # margin*leverage of notional. size is the leveraged coin qty so PnL = size*Δprice
                # scales with leverage (real Hyperliquid behaviour). Fees are charged on the FULL
                # leveraged notional. Exposure/cash stay in margin terms (caps still protect 1000$).
                margin_usdt = desired_notional
                notional = desired_notional * simulation_leverage
                size = notional / float(row.price)
                cost = notional * cost_bps / 10_000.0
                expected_net_edge_usdt = notional * safe_float(metrics.get("edge_remaining_bps"), 0.0) / 10_000.0
                roundtrip_cost_estimate_usdt = cost * 2.0
                # edge_remaining_bps is already net of fee/spread/slippage in
                # the realtime scorer. Do not require the same round-trip cost
                # a second time here, otherwise valid small-notional 1000 USDT
                # simulation entries are rejected even after the edge gate has
                # accepted them.
                # V9: edge_remaining_bps is the primary gate. Keep a dust guard,
                # but make it small enough for a 1000 USDT paper account to
                # take bounded consensus opportunities instead of starving.
                minimum_edge_usdt = calibrated_float_env(
                    "HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT",
                    max(0.02, starting_equity_usdt * 0.00002),
                )
                if expected_net_edge_usdt < minimum_edge_usdt:
                    event.update(
                        {
                            "reason": "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS",
                            "expected_net_edge_usdt": round(expected_net_edge_usdt, 6),
                            "roundtrip_cost_estimate_usdt": round(roundtrip_cost_estimate_usdt, 6),
                            "minimum_edge_usdt": round(minimum_edge_usdt, 6),
                            "fee_drag_guard": True,
                        }
                    )
                    ledger_events.append(event)
                    continue
                previous = positions.get(key, {"size": 0.0, "avg_price": 0.0, "entry_costs": 0.0})
                previous_key_existed = key in positions
                previous_snapshot = dict(previous)
                was_existing_position = float(previous.get("size") or 0.0) > 0
                position_mode = str(metrics.get("position_mode") or "SINGLE_LEADER")
                cluster_id = str(metrics.get("consensus_cluster_id") or "").lower()
                previous_clusters = csv_to_set(previous.get("seen_cluster_ids_csv"))
                if position_mode == "CONSENSUS_CLUSTER" and previous["size"] > 0 and cluster_id in previous_clusters:
                    leader_wallets = csv_to_set(previous.get("leader_wallets_csv"))
                    leader_wallets.update(csv_to_set(metrics.get("consensus_wallets_csv")))
                    leader_wallets.add(row.wallet_address.lower())
                    previous["leader_wallets_csv"] = set_to_csv(leader_wallets)
                    event.update(
                        {
                            "bot_replay_action": "CONSENSUS_DUPLICATE_IGNORED",
                            "status": "REFUSED",
                            "estimated_net_pnl_usdc": None,
                            "bot_position_size_after": round(float(previous["size"]), 10),
                            "reason": "CONSENSUS_CLUSTER_ALREADY_OPEN_NO_EXTRA_SIZE",
                        }
                    )
                    ledger_events.append(event)
                    continue
                signal_age_for_join = (
                    max_signal_age_ms + 1
                    if signal_age_value is None
                    else int(signal_age_value)
                )
                join_add_as_entry = (
                    allow_add_as_entry
                    and action in {"ADD", "INCREASE"}
                    and previous["size"] <= 0
                    and int(metrics.get("consensus_wallets") or 0) >= 3
                    and signal_age_for_join <= max_signal_age_ms
                    and metrics.get("decision_reason") == "EDGE_OK_FOR_LOCAL_SIMULATION"
                )
                if action in {"ADD", "INCREASE"} and previous["size"] <= 0 and not join_add_as_entry:
                    event["reason"] = "ADD_WITHOUT_ORIGINAL_OPEN_REFUSED"
                    ledger_events.append(event)
                    continue
                elif len(positions) >= max_open_positions and previous["size"] <= 0:
                    event["reason"] = "MAX_VIRTUAL_POSITIONS_REACHED"
                    ledger_events.append(event)
                    continue
                new_size = previous["size"] + size
                avg_price = (
                    ((previous["avg_price"] * previous["size"]) + (float(row.price) * size)) / new_size
                    if new_size > 0
                    else float(row.price)
                )
                leader_wallets = csv_to_set(previous.get("leader_wallets_csv"))
                leader_wallets.update(csv_to_set(metrics.get("consensus_wallets_csv")))
                leader_wallets.add(row.wallet_address.lower())
                seen_cluster_ids = csv_to_set(previous.get("seen_cluster_ids_csv"))
                if cluster_id:
                    seen_cluster_ids.add(cluster_id)
                positions[key] = {
                    "size": new_size,
                    "avg_price": avg_price,
                    "entry_costs": previous["entry_costs"] + cost,
                    "highest_price": max(previous.get("highest_price", avg_price), float(row.price)),
                    "lowest_price": min(previous.get("lowest_price", avg_price), float(row.price)),
                    "opened_at_ms": previous.get("opened_at_ms", delta_event_time_ms(row) or current_ms),
                    "last_update_at_ms": delta_event_time_ms(row) or current_ms,
                    "source_delta_key": previous.get("source_delta_key") or current_delta_key,
                    "position_mode": position_mode,
                    "leader_wallets_csv": set_to_csv(leader_wallets),
                    "closed_wallets_csv": str(previous.get("closed_wallets_csv") or ""),
                    "seen_cluster_ids_csv": set_to_csv(seen_cluster_ids),
                    "last_cluster_id": cluster_id,
                    "last_reduce_fraction": float(previous.get("last_reduce_fraction") or 0.0),
                    "last_notional_closed_usdt": float(previous.get("last_notional_closed_usdt") or 0.0),
                    "entry_count": int(previous.get("entry_count") or 0) + (0 if was_existing_position else 1),
                    "increase_count": int(previous.get("increase_count") or 0) + (1 if was_existing_position else 0),
                    "reduce_count": int(previous.get("reduce_count") or 0),
                }
                if row.source == "fresh_opportunity_cluster_local_simulation":
                    raw_json = row.raw_json if isinstance(row.raw_json, dict) else {}
                    source_delta_keys = raw_json.get("cluster_source_delta_keys")
                    if isinstance(source_delta_keys, list):
                        for source_delta_key in source_delta_keys:
                            if isinstance(source_delta_key, str) and source_delta_key:
                                processed_keys.add(source_delta_key)
                if action.startswith("OPEN"):
                    replay_action = "PAPER_CONSENSUS_ENTRY_REPLAYED" if position_mode == "CONSENSUS_CLUSTER" else "PAPER_ENTRY_REPLAYED"
                    replay_reason = (
                        "CONSENSUS_CLUSTER_ENTRY_LOCAL_REPLAY_ONLY"
                        if position_mode == "CONSENSUS_CLUSTER"
                        else "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT"
                    )
                elif join_add_as_entry:
                    replay_action = "PAPER_CONSENSUS_ADD_ENTRY_REPLAYED" if position_mode == "CONSENSUS_CLUSTER" else "PAPER_JOIN_ADD_AS_ENTRY"
                    replay_reason = (
                        "JOINED_MULTI_WALLET_CONSENSUS_CLUSTER_AS_LOCAL_ENTRY_NOT_ORDER"
                        if position_mode == "CONSENSUS_CLUSTER"
                        else "JOINED_MULTI_WALLET_CONSENSUS_ADD_AS_LOCAL_ENTRY_NOT_ORDER"
                    )
                else:
                    replay_action = "PAPER_CONSENSUS_ADD_REPLAYED" if position_mode == "CONSENSUS_CLUSTER" else "PAPER_ADD_REPLAYED"
                    replay_reason = (
                        "CONSENSUS_CLUSTER_ADD_LOCAL_REPLAY_ONLY"
                        if position_mode == "CONSENSUS_CLUSTER"
                        else "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT"
                    )
                event.update(
                    {
                        "bot_replay_action": replay_action,
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": round(-cost, 6),
                        "fee_cost_usdc": round(cost, 6),
                        "bot_position_size_after": round(new_size, 10),
                        "copied_notional_usdt": round(notional, 6),
                        "reason": event.get("reason") or replay_reason,
                        "position_mode": position_mode,
                        "leader_wallets_csv": set_to_csv(leader_wallets),
                        "paper_action_type": "INCREASE" if was_existing_position else "OPEN",
                        "entry_price": round(float(row.price), 8),
                        "average_entry_price": round(avg_price, 8),
                        "avg_entry_price_after": round(avg_price, 8),
                        "position_notional_usdt": round(new_size * avg_price, 6),
                        "size_before": round(float(previous.get("size") or 0.0), 10),
                        "size_added": round(size, 10),
                        "size_after": round(new_size, 10),
                    }
                )
                enrich_replay_evidence(event, position_key=key, replay_action=replay_action)
                if v9_pipeline_authoritative and event.get("v9_accepted") is False:
                    if previous_key_existed:
                        positions[key] = previous_snapshot
                    else:
                        positions.pop(key, None)
                    v9_reason = (
                        "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS"
                        if str(event.get("v9_decision") or "").upper() == "REJECT_EDGE_TOO_SMALL"
                        else "V9_PIPELINE_REFUSED_ENTRY"
                    )
                    event.update(
                        {
                            "bot_replay_action": "NO_TRADE",
                            "status": "REFUSED",
                            "estimated_net_pnl_usdc": None,
                            "fee_cost_usdc": 0.0,
                            "bot_position_size_after": round(float(previous_snapshot.get("size") or 0.0), 10),
                            "reason": v9_reason,
                            "v9_authoritative": True,
                            "paper_action_type": "NO_TRADE",
                        }
                    )
                    ledger_events.append(event)
                    continue
                positions[key]["last_replay_action"] = replay_action
                positions[key]["last_evidence_hash"] = str(event.get("evidence_hash") or "")
                positions[key]["last_paper_ref"] = str(event.get("paper_ref") or "")
                positions[key]["last_v9_decision"] = str(event.get("v9_decision") or "")
                positions[key]["last_v9_evidence_hash"] = str(event.get("v9_evidence_hash") or "")
                positions[key]["last_v9_reasons"] = list(event.get("v9_reasons") or [])
                ledger_events.append(event)
                continue

            if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
                key = position_key_for_row(row, direction, action, metrics)
                event["matched_position_key"] = encode_position_key(*key)
                previous = positions.get(key)
                if previous is None or previous["size"] <= 0:
                    event["reason"] = "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
                    ledger_events.append(event)
                    continue
                signal_age_for_exit = (
                    max_signal_age_ms + 1
                    if signal_age_value is None
                    else int(signal_age_value)
                )
                # Exit signals are allowed with a much larger window (10x) vs entries:
                # once the bot has an open paper position, it must be able to close it
                # when the leader closes, regardless of how old the signal is.
                if signal_age_for_exit > max_signal_age_ms * 10:
                    event["reason"] = "STALE_EXIT_SIGNAL"
                    ledger_events.append(event)
                    continue
                position_mode = str(previous.get("position_mode") or ("CONSENSUS_CLUSTER" if key[0] == "__consensus__" else "SINGLE_LEADER"))
                leader_wallets = csv_to_set(previous.get("leader_wallets_csv"))
                closed_wallets = csv_to_set(previous.get("closed_wallets_csv"))
                if position_mode == "CONSENSUS_CLUSTER" and leader_wallets and row.wallet_address.lower() not in leader_wallets:
                    event["reason"] = "NO_MATCHING_CONSENSUS_LEADER_FOR_CLOSE"
                    ledger_events.append(event)
                    continue
                size = abs(float(row.delta_size or row.fill_size or previous["size"]))
                if position_mode == "CONSENSUS_CLUSTER":
                    remaining_leaders = leader_wallets - closed_wallets if leader_wallets else set()
                    remaining_count = max(1, len(remaining_leaders))
                    if action.startswith("CLOSE"):
                        closed_after = set(closed_wallets)
                        closed_after.add(row.wallet_address.lower())
                        close_size = previous["size"] if leader_wallets and leader_wallets.issubset(closed_after) else previous["size"] / remaining_count
                        closed_wallets = closed_after
                    else:
                        leader_reduce_fraction = (
                            min(1.0, max(0.05, size / abs(float(row.previous_size or 0.0))))
                            if row.previous_size
                            else 0.5
                        )
                        close_size = min(previous["size"], (previous["size"] / remaining_count) * leader_reduce_fraction)
                else:
                    close_size = previous["size"] if action.startswith("CLOSE") or size <= 0 else min(previous["size"], size)
                if direction == "LONG":
                    gross_pnl = (float(row.price) - previous["avg_price"]) * close_size
                else:
                    gross_pnl = (previous["avg_price"] - float(row.price)) * close_size
                exit_cost = close_size * float(row.price) * cost_bps / 10_000.0
                allocated_entry_cost = previous["entry_costs"] * (close_size / previous["size"])
                # Entry costs are recorded when a virtual entry is opened; close events
                # only subtract exit costs to avoid double-counting fees in the graph.
                net_pnl = gross_pnl - exit_cost
                remaining_size = max(0.0, previous["size"] - close_size)
                close_fraction = (close_size / previous["size"]) if previous["size"] > 0 else 0.0
                if remaining_size <= 1e-12:
                    positions.pop(key, None)
                else:
                    positions[key] = {
                        "size": remaining_size,
                        "avg_price": previous["avg_price"],
                        "entry_costs": previous["entry_costs"] - allocated_entry_cost,
                        "highest_price": previous.get("highest_price", previous["avg_price"]),
                        "lowest_price": previous.get("lowest_price", previous["avg_price"]),
                        "opened_at_ms": previous.get("opened_at_ms", delta_event_time_ms(row) or current_ms),
                        "last_update_at_ms": delta_event_time_ms(row) or current_ms,
                        "source_delta_key": previous.get("source_delta_key", ""),
                        "position_mode": position_mode,
                        "leader_wallets_csv": set_to_csv(leader_wallets),
                        "closed_wallets_csv": set_to_csv(closed_wallets),
                        "seen_cluster_ids_csv": str(previous.get("seen_cluster_ids_csv") or ""),
                        "last_cluster_id": str(previous.get("last_cluster_id") or ""),
                        "last_reduce_fraction": close_fraction,
                        "last_notional_closed_usdt": close_size * float(row.price),
                        "entry_count": int(previous.get("entry_count") or 0),
                        "increase_count": int(previous.get("increase_count") or 0),
                        "reduce_count": int(previous.get("reduce_count") or 0) + 1,
                    }
                replay_action = (
                    "PAPER_CONSENSUS_CLOSE_REPLAYED"
                    if action.startswith("CLOSE") and position_mode == "CONSENSUS_CLUSTER"
                    else "PAPER_CLOSE_REPLAYED"
                    if action.startswith("CLOSE")
                    else "PAPER_CONSENSUS_REDUCE_REPLAYED"
                    if position_mode == "CONSENSUS_CLUSTER"
                    else "PAPER_REDUCE_REPLAYED"
                )
                event.update(
                    {
                        "bot_replay_action": replay_action,
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": round(net_pnl, 6),
                        "gross_pnl_usdc": round(gross_pnl, 6),
                        "fee_cost_usdc": round(exit_cost, 6),
                        "bot_position_size_after": round(remaining_size, 10),
                        "copied_notional_usdt": round(close_size * float(row.price), 6),
                        "reason": "LOCAL_REPLAY_ONLY_NOT_AN_ORDER",
                        "position_mode": position_mode,
                        "leader_wallets_csv": set_to_csv(leader_wallets),
                        "closed_wallets_csv": set_to_csv(closed_wallets),
                        "paper_action_type": "CLOSE" if action.startswith("CLOSE") else "REDUCE",
                        "average_entry_price": round(float(previous["avg_price"]), 8),
                        "exit_price": round(float(row.price), 8),
                        "notional_closed_usdt": round(close_size * float(row.price), 6),
                        "remaining_notional_usdt": round(remaining_size * float(row.price), 6),
                        "reduce_fraction": round(close_fraction, 6),
                        "size_before": round(float(previous["size"]), 10),
                        "size_closed": round(close_size, 10),
                        "size_after": round(remaining_size, 10),
                    }
                )
                enrich_replay_evidence(event, position_key=key, replay_action=replay_action)
                if key in positions:
                    positions[key]["last_replay_action"] = replay_action
                    positions[key]["last_evidence_hash"] = str(event.get("evidence_hash") or "")
                    positions[key]["last_paper_ref"] = str(event.get("paper_ref") or "")
                    positions[key]["last_v9_decision"] = str(event.get("v9_decision") or "")
                    positions[key]["last_v9_evidence_hash"] = str(event.get("v9_evidence_hash") or "")
                    positions[key]["last_v9_reasons"] = list(event.get("v9_reasons") or [])
                ledger_events.append(event)
                continue

            event["reason"] = "UNSUPPORTED_DELTA_FOR_REPLAY"
            ledger_events.append(event)

        mid_prices = mid_prices or {}
        # V9 — sortie disciplinee SL/TP (scalping) au PRIX REEL, independante du leader: encaisse
        # vite un petit gain (take-profit) et coupe vite une perte (stop-loss), pour la distribution
        # "beaucoup de petits gains". Le PnL est realise au vrai mid courant (= ce qu'un ordre TP/SL
        # aurait capture), donc honnete. Non bloquant. Pilotable par env HYPERSMART_SLTP_*.
        # Desactive par defaut en V12: la simulation baseline suit les reduce/close leaders.
        sltp_runtime_cfg = None
        try:
            from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits, sltp_config_from_env
            sltp_runtime_cfg = sltp_config_from_env()
            apply_sltp_exits(positions, ledger_events, mid_prices, cost_bps=cost_bps, now_ms=current_ms, config=sltp_runtime_cfg)
        except Exception:
            sltp_runtime_cfg = None
            pass
        open_positions: list[dict[str, Any]] = []
        unrealized_pnl = 0.0
        open_exposure_usdt = 0.0
        open_notional_usdt = 0.0
        persisted_positions: dict[str, dict[str, Any]] = {}
        for (wallet, coin, direction), position in positions.items():
            mark_price = mid_prices.get(coin)
            if mark_price is None:
                mark_price = position["avg_price"]
            position_notional = abs(position["size"] * mark_price)      # leveraged notional (true HL size)
            position_margin = position_notional / simulation_leverage    # capital deployed (margin at risk)
            open_exposure_usdt += position_margin
            open_notional_usdt += position_notional
            if direction == "LONG":
                gross_unrealized = (mark_price - position["avg_price"]) * position["size"]
            else:
                gross_unrealized = (position["avg_price"] - mark_price) * position["size"]
            exit_cost_estimate = abs(position["size"] * mark_price) * cost_bps / 10_000.0
            net_unrealized = gross_unrealized - exit_cost_estimate
            unrealized_pnl += net_unrealized
            open_positions.append(
                {
                    "wallet_address": wallet,
                    "coin": coin,
                    "direction": direction,
                    "position_mode": position.get("position_mode") or ("CONSENSUS_CLUSTER" if wallet == "__consensus__" else "SINGLE_LEADER"),
                    "leader_wallets_count": len(csv_to_set(position.get("leader_wallets_csv"))),
                    "closed_wallets_count": len(csv_to_set(position.get("closed_wallets_csv"))),
                    "size": round(position["size"], 10),
                    "avg_entry_price": round(position["avg_price"], 8),
                    "mark_price": round(mark_price, 8),
                    "notional_usdt": round(position_notional, 6),
                    "margin_usdt": round(position_margin, 6),
                    "leverage": round(simulation_leverage, 2),
                    "entry_costs_remaining": round(position["entry_costs"], 6),
                    "unrealized_pnl_usdc": round(net_unrealized, 6),
                    "opened_at_ms": int(position.get("opened_at_ms") or 0),
                    "last_update_at_ms": int(position.get("last_update_at_ms") or 0),
                    "source_delta_key": str(position.get("source_delta_key") or ""),
                    "last_replay_action": str(position.get("last_replay_action") or ""),
                    "last_evidence_hash": str(position.get("last_evidence_hash") or ""),
                    "last_paper_ref": str(position.get("last_paper_ref") or ""),
                    "last_v9_decision": str(position.get("last_v9_decision") or ""),
                    "last_v9_evidence_hash": str(position.get("last_v9_evidence_hash") or ""),
                    "last_v9_reasons": list(position.get("last_v9_reasons") or []),
                    "last_reduce_fraction": round(float(position.get("last_reduce_fraction") or 0.0), 6),
                    "last_notional_closed_usdt": round(float(position.get("last_notional_closed_usdt") or 0.0), 6),
                    "entry_count": int(position.get("entry_count") or 0),
                    "increase_count": int(position.get("increase_count") or 0),
                    "reduce_count": int(position.get("reduce_count") or 0),
                    "research_only": True,
                }
            )
            persisted_positions[encode_position_key(wallet, coin, direction)] = {
                "wallet_address": wallet,
                "coin": coin,
                "direction": direction,
                "size": round(float(position["size"]), 12),
                "avg_price": round(float(position["avg_price"]), 12),
                "entry_costs": round(float(position["entry_costs"]), 12),
                "highest_price": round(float(position.get("highest_price", position["avg_price"])), 12),
                "lowest_price": round(float(position.get("lowest_price", position["avg_price"])), 12),
                "opened_at_ms": int(position.get("opened_at_ms") or 0),
                "last_update_at_ms": int(position.get("last_update_at_ms") or 0),
                "source_delta_key": str(position.get("source_delta_key") or ""),
                "position_mode": str(position.get("position_mode") or ("CONSENSUS_CLUSTER" if wallet == "__consensus__" else "SINGLE_LEADER")),
                "leader_wallets_csv": str(position.get("leader_wallets_csv") or wallet),
                "closed_wallets_csv": str(position.get("closed_wallets_csv") or ""),
                "seen_cluster_ids_csv": str(position.get("seen_cluster_ids_csv") or ""),
                "last_cluster_id": str(position.get("last_cluster_id") or ""),
                "last_replay_action": str(position.get("last_replay_action") or ""),
                "last_evidence_hash": str(position.get("last_evidence_hash") or ""),
                "last_paper_ref": str(position.get("last_paper_ref") or ""),
                "last_v9_decision": str(position.get("last_v9_decision") or ""),
                "last_v9_evidence_hash": str(position.get("last_v9_evidence_hash") or ""),
                "last_v9_reasons": list(position.get("last_v9_reasons") or []),
                "last_reduce_fraction": round(float(position.get("last_reduce_fraction") or 0.0), 12),
                "last_notional_closed_usdt": round(float(position.get("last_notional_closed_usdt") or 0.0), 12),
                "entry_count": int(position.get("entry_count") or 0),
                "increase_count": int(position.get("increase_count") or 0),
                "reduce_count": int(position.get("reduce_count") or 0),
            }
        open_positions.sort(key=lambda item: abs(float(item["unrealized_pnl_usdc"])), reverse=True)
        display_ledger_events = ledger_events[-max_events:]
        important_ledger_events = [
            row
            for row in ledger_events
            if row.get("status") == "LOCAL_REPLAY"
        ][-120:]
        new_ledger_events = ledger_events[initial_ledger_length:]
        new_realized_delta = sum(
            float(row.get("estimated_net_pnl_usdc") or 0.0)
            for row in new_ledger_events
            if row.get("status") == "LOCAL_REPLAY"
        )
        realized_net_pnl = float(existing_realized_pnl_usdc or 0.0) + new_realized_delta
        new_entry_costs_paid = sum(
            float(row.get("fee_cost_usdc") or 0.0)
            for row in new_ledger_events
            if row.get("bot_replay_action") in entry_replay_actions
        )
        new_exit_costs_paid = sum(
            float(row.get("fee_cost_usdc") or 0.0)
            for row in new_ledger_events
            if row.get("bot_replay_action") in exit_replay_actions
        )
        entry_costs_paid = float(existing_entry_costs_paid_usdc or 0.0) + new_entry_costs_paid
        exit_costs_paid = float(existing_exit_costs_paid_usdc or 0.0) + new_exit_costs_paid
        new_reproduced_entries = sum(
            1
            for row in new_ledger_events
            if row.get("bot_replay_action") in entry_replay_actions
        )
        new_reproduced_exits = sum(
            1
            for row in new_ledger_events
            if row.get("bot_replay_action") in exit_replay_actions
        )
        reproduced_entries = int(existing_reproduced_entries_total or 0) + new_reproduced_entries
        reproduced_exits = int(existing_reproduced_exits_total or 0) + new_reproduced_exits
        refused = sum(1 for row in ledger_events if row.get("status") == "REFUSED")
        total_pnl = realized_net_pnl + unrealized_pnl
        current_equity_usdt = starting_equity_usdt + total_pnl
        free_equity_usdt = current_equity_usdt - open_exposure_usdt
        exposure_pct = (open_exposure_usdt / current_equity_usdt * 100.0) if current_equity_usdt > 0 else 0.0
        # Winrate par POSITION (round-trip), PAS par event. BUG 2026-06-26: on comptait chaque
        # REDUCE partiel comme un "trade" -> une position reduite 9x = 9 trades (souvent comptes
        # perdants) -> winrate FAUSSEMENT bas. Correct: on somme le PnL realise par
        # matched_position_key et on classe gagnant/perdant sur le TOTAL de la position.
        _pos_pnls: dict[str, float] = {}
        for row in ledger_events:
            if row.get("status") != "LOCAL_REPLAY" or row.get("bot_replay_action") not in exit_replay_actions:
                continue
            _k = str(row.get("matched_position_key") or row.get("coin") or "")
            _pos_pnls[_k] = _pos_pnls.get(_k, 0.0) + float(row.get("estimated_net_pnl_usdc") or 0.0)
        _round_trip = list(_pos_pnls.values())
        winning_trades = sum(1 for _p in _round_trip if _p > 0)
        losing_trades = sum(1 for _p in _round_trip if _p < 0)
        closed_trades = sum(1 for _p in _round_trip if _p != 0)
        winrate_pct = round(winning_trades / closed_trades * 100.0, 1) if closed_trades else 0.0
        # Profit factor = gains totaux / pertes totales. C'est LA metrique qui compte pour une
        # strategie "coupe les perdants / laisse courir les gagnants": un winrate <50% est NORMAL
        # et RENTABLE tant que profit_factor > 1 (les gagnants pesent plus que les perdants).
        _gross_win = sum(_p for _p in _round_trip if _p > 0)
        _gross_loss = -sum(_p for _p in _round_trip if _p < 0)
        profit_factor = round(_gross_win / _gross_loss, 3) if _gross_loss > 0 else None
        avg_win_usdc = round(_gross_win / winning_trades, 6) if winning_trades else 0.0
        avg_loss_usdc = round(-_gross_loss / losing_trades, 6) if losing_trades else 0.0

        return {
            "events": list(reversed(display_ledger_events[-240:])),
            "important_events": list(reversed(important_ledger_events[-120:])),
            "ledger_events": ledger_events,
            "new_ledger_events": new_ledger_events,
            "processed_delta_keys": sorted(processed_keys)[-10_000:],
            "virtual_positions_state": persisted_positions,
            "reproduced_entries": reproduced_entries,
            "reproduced_exits": reproduced_exits,
            "refused": refused,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "closed_trades": closed_trades,
            "winrate_pct": winrate_pct,
            "profit_factor": profit_factor,
            "avg_win_usdc": avg_win_usdc,
            "avg_loss_usdc": avg_loss_usdc,
            "open_local_positions": len(positions),
            "open_positions": open_positions[:25],
            "realized_net_pnl_usdc": round(realized_net_pnl, 6),
            "unrealized_pnl_usdc": round(unrealized_pnl, 6),
            "estimated_net_pnl_usdc": round(total_pnl, 6),
            "starting_equity_usdt": round(starting_equity_usdt, 6),
            "current_equity_usdt": round(current_equity_usdt, 6),
            "free_equity_usdt": round(free_equity_usdt, 6),
            "open_exposure_usdt": round(open_exposure_usdt, 6),
            "open_notional_usdt": round(open_notional_usdt, 6),
            "leverage": round(simulation_leverage, 2),
            "open_exposure_pct": round(exposure_pct, 6),
            "entry_costs_paid_usdc": round(entry_costs_paid, 6),
            "exit_costs_paid_usdc": round(exit_costs_paid, 6),
            "total_costs_paid_usdc": round(entry_costs_paid + exit_costs_paid, 6),
            "new_realized_delta_usdc": round(new_realized_delta, 6),
            "new_reproduced_entries": new_reproduced_entries,
            "new_reproduced_exits": new_reproduced_exits,
            "cost_model_bps": cost_bps,
            "filter_diagnostics": dict(filter_diagnostics),
            "fresh_entry_diagnostics": dict(fresh_entry_diagnostics),
            "prefilter_skips": prefilter_skips[-120:],
            "prefilter_skip_count": len(prefilter_skips),
            "magic_profile": {
                "mode": "fresh_leader_following_simulation",
                "starting_equity_usdt": starting_equity_usdt,
                "max_position_notional_usdt": max_position_notional_usdt,
                "max_open_positions": max_open_positions,
                "min_edge_required_bps": min_edge_required_bps,
                "max_signal_age_seconds": int(max_signal_age_ms / 1000),
                "consensus_window_seconds": int(consensus_window_ms / 1000),
                "consensus_policy": "boost if several leaders open same coin/side in the fresh window; 4s clusters are strongest; solo entries require stronger edge and fresh timing",
                "adaptive_loss_cooldown_policy": "new entries pause on coins/leaders losing in this session unless 3+ wallets form a fresh consensus",
                "consensus_position_policy": "one shared local position per coin/side consensus cluster; duplicate leaders confirm the cluster instead of multiplying exposure",
                "entries_allowed": (
                    ["OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"]
                    if allow_add_as_entry
                    else ["OPEN_LONG", "OPEN_SHORT"]
                ),
                "add_policy": (
                    "ADD/INCREASE can create a first local entry only when 3+ leaders form a fresh same-coin/same-side consensus and edge gates pass"
                    if allow_add_as_entry
                    else "ADD/INCREASE allowed only when the bot already has the matching virtual position; it cannot create an initial entry because the original open was missed"
                ),
                "holding_policy": "hold_until_matching_leader_reduce_or_close; calibrated local SL/TP can close paper positions at real marks when enabled",
                "stop_loss_policy": (
                    f"enabled_at_{sltp_runtime_cfg.stop_loss_bps}_bps_real_mark_local_paper"
                    if sltp_runtime_cfg
                    else "disabled; no local stop-loss without env opt-in"
                ),
                "take_profit_policy": (
                    f"enabled_at_{sltp_runtime_cfg.take_profit_bps}_bps_real_mark_local_paper"
                    if sltp_runtime_cfg
                    else "disabled; no local take-profit without env opt-in"
                ),
                "trailing_stop_policy": (
                    f"enabled_at_{sltp_runtime_cfg.trailing_stop_bps}_bps_real_mark_local_paper"
                    if sltp_runtime_cfg and sltp_runtime_cfg.trailing_stop_bps is not None
                    else "disabled; no local trailing stop without env opt-in"
                ),
                "red_pnl_exit_policy": "never_exit_only_because_unrealized_pnl_is_negative",
                "execution": "forbidden",
            },
            "message": "Simulation locale sans argent: le bot ouvre/ferme des positions virtuelles sur deltas leaders frais, exige un edge mesurable, applique les couts, sans execution reelle ni garantie.",
        }

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

    def compact_bot_simulation_for_api(bot: dict[str, Any]) -> dict[str, Any]:
        hidden_keys = {
            "ledger_events",
            "new_ledger_events",
            "processed_delta_keys",
            "virtual_positions_state",
            "new_ledger_events",
        }
        compact = {
            key: value
            for key, value in bot.items()
            if key not in hidden_keys
        }
        compact["events"] = list(bot.get("events") or [])[:60]
        compact["open_positions"] = list(bot.get("open_positions") or [])[:25]
        compact["api_payload_compacted"] = True
        compact["full_details_location"] = "logs/logs a envoyer"
        return compact

    def initial_simulation_equity_point(timestamp_ms: int | None = None) -> dict[str, Any]:
        return {
            "timestamp_ms": int(timestamp_ms or state.simulation_started_at_ms or now_ms()),
            "current_pnl_usdc": 0.0,
            "current_equity_usdt": round(float(state.simulation_starting_equity_usdt or 1000.0), 6),
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "open_exposure_usdt": 0.0,
            "open_positions": 0,
            "source": "SESSION_START",
        }

    def simulation_equity_point(bot_simulation: dict[str, Any], timestamp_ms: int) -> dict[str, Any]:
        open_positions_count = int(bot_simulation.get("open_local_positions") or 0)
        return {
            "timestamp_ms": int(timestamp_ms),
            "current_pnl_usdc": round(float(bot_simulation.get("estimated_net_pnl_usdc") or 0.0), 6),
            "current_equity_usdt": round(float(bot_simulation.get("current_equity_usdt") or state.simulation_starting_equity_usdt), 6),
            "realized_pnl_usdc": round(float(bot_simulation.get("realized_net_pnl_usdc") or 0.0), 6),
            "unrealized_pnl_usdc": round(float(bot_simulation.get("unrealized_pnl_usdc") or 0.0), 6),
            "open_exposure_usdt": round(float(bot_simulation.get("open_exposure_usdt") or 0.0), 6),
            "open_positions": open_positions_count,
            "reproduced_entries": int(bot_simulation.get("reproduced_entries") or 0),
            "reproduced_exits": int(bot_simulation.get("reproduced_exits") or 0),
            "refused": int(bot_simulation.get("refused") or 0),
            "source": "MARK_TO_MARKET" if open_positions_count else "SESSION_EQUITY",
        }

    def append_simulation_equity_history(bot_simulation: dict[str, Any], timestamp_ms: int) -> None:
        if not state.simulation_equity_history:
            state.simulation_equity_history.append(initial_simulation_equity_point(state.simulation_started_at_ms))

        def append_point(point: dict[str, Any], *, force: bool = False) -> None:
            last = state.simulation_equity_history[-1]
            last_ts = int(last.get("timestamp_ms") or 0)
            point_ts = int(point.get("timestamp_ms") or timestamp_ms)
            if point_ts <= last_ts:
                point_ts = last_ts + 1
                point["timestamp_ms"] = point_ts
            changed = any(
                abs(float(point.get(key) or 0.0) - float(last.get(key) or 0.0)) > 1e-9
                for key in ("current_pnl_usdc", "current_equity_usdt", "realized_pnl_usdc", "unrealized_pnl_usdc", "open_exposure_usdt")
            ) or int(point.get("open_positions") or 0) != int(last.get("open_positions") or 0)
            elapsed_enough = point_ts - last_ts >= 1_000
            if force or changed or elapsed_enough:
                state.simulation_equity_history.append(point)
                state.simulation_equity_history[:] = state.simulation_equity_history[-5_000:]

        for event in sorted(bot_simulation.get("new_ledger_events") or [], key=lambda item: int(item.get("observed_at_ms") or 0)):
            if not isinstance(event, dict) or event.get("estimated_net_pnl_usdc") is None:
                continue
            if event.get("status") != "LOCAL_REPLAY":
                continue
            previous = state.simulation_equity_history[-1]
            next_pnl = float(previous.get("current_pnl_usdc") or 0.0) + float(event.get("estimated_net_pnl_usdc") or 0.0)
            append_point(
                {
                    "timestamp_ms": int(event.get("observed_at_ms") or timestamp_ms),
                    "current_pnl_usdc": round(next_pnl, 6),
                    "current_equity_usdt": round(float(state.simulation_starting_equity_usdt or 1000.0) + next_pnl, 6),
                    "realized_pnl_usdc": round(next_pnl, 6),
                    "unrealized_pnl_usdc": 0.0,
                    "open_exposure_usdt": previous.get("open_exposure_usdt") or 0.0,
                    "open_positions": previous.get("open_positions") or 0,
                    "source": event.get("bot_replay_action") or "LOCAL_REPLAY",
                    "source_delta_key": event.get("delta_key"),
                    "wallet_address": event.get("wallet_address"),
                    "coin": event.get("coin"),
                },
                force=True,
            )
        append_point(simulation_equity_point(bot_simulation, timestamp_ms))

    def build_session_equity_candles(history: list[dict[str, Any]], *, max_points: int = 240) -> list[dict[str, Any]]:
        points = [
            row
            for row in sorted(history, key=lambda item: int(item.get("timestamp_ms") or 0))
            if isinstance(row, dict) and row.get("current_pnl_usdc") is not None
        ]
        if len(points) < 2:
            return []
        if len(points) > max_points + 1:
            points = points[-(max_points + 1):]
        candles: list[dict[str, Any]] = []
        previous_ha_open: float | None = None
        previous_ha_close: float | None = None
        for index in range(1, len(points)):
            previous = points[index - 1]
            row = points[index]
            open_value = float(previous.get("current_pnl_usdc") or 0.0)
            close_value = float(row.get("current_pnl_usdc") or 0.0)
            high_value = max(open_value, close_value)
            low_value = min(open_value, close_value)
            ha_close = (open_value + high_value + low_value + close_value) / 4.0
            ha_open = (open_value + close_value) / 2.0 if previous_ha_open is None else (previous_ha_open + previous_ha_close) / 2.0
            ha_high = max(high_value, ha_open, ha_close)
            ha_low = min(low_value, ha_open, ha_close)
            previous_ha_open = ha_open
            previous_ha_close = ha_close
            candles.append(
                {
                    "index": len(candles),
                    "wallet_address": "simulation",
                    "coin": "PORTEFEUILLE",
                    "timestamp_ms": row.get("timestamp_ms"),
                    "pnl_usdc": round(close_value - open_value, 6),
                    "equity_open": round(open_value, 6),
                    "equity_close": round(close_value, 6),
                    "ha_open": round(ha_open, 6),
                    "ha_high": round(ha_high, 6),
                    "ha_low": round(ha_low, 6),
                    "ha_close": round(ha_close, 6),
                    "color": "green" if close_value >= open_value else "red",
                    "source": row.get("source") or "session_equity_history",
                    "current_equity_usdt": row.get("current_equity_usdt"),
                    "realized_pnl_usdc": row.get("realized_pnl_usdc"),
                    "unrealized_pnl_usdc": row.get("unrealized_pnl_usdc"),
                    "open_exposure_usdt": row.get("open_exposure_usdt"),
                }
            )
        return candles

    def build_pnl_consistency(equity: dict[str, Any]) -> dict[str, Any]:
        starting = safe_float(equity.get("starting_equity_usdt"), 1000.0)
        realized = safe_float(equity.get("realized_pnl_usdc"), 0.0)
        unrealized = safe_float(equity.get("unrealized_pnl_usdc"), 0.0)
        reported_total = safe_float(equity.get("current_pnl_usdc"), 0.0)
        reported_equity = safe_float(equity.get("current_equity_usdt"), starting)
        recomputed_total = round(realized + unrealized, 6)
        recomputed_equity = round(starting + recomputed_total, 6)
        pnl_delta = round(reported_total - recomputed_total, 6)
        equity_delta = round(reported_equity - recomputed_equity, 6)
        ok = abs(pnl_delta) <= 0.00001 and abs(equity_delta) <= 0.00001
        return {
            "status": "OK" if ok else "MISMATCH",
            "ok": ok,
            "starting_equity_usdt": round(starting, 6),
            "reported_total_pnl_usdc": round(reported_total, 6),
            "reported_equity_usdt": round(reported_equity, 6),
            "recomputed_total_pnl_usdc": recomputed_total,
            "recomputed_equity_usdt": recomputed_equity,
            "realized_pnl_usdc": round(realized, 6),
            "unrealized_pnl_usdc": round(unrealized, 6),
            "pnl_delta_usdc": pnl_delta,
            "equity_delta_usdt": equity_delta,
            "beginner_formula": "solde fictif = capital depart + gain/perte encaisse + gain/perte en cours",
            "display_note": (
                "Le solde affiche est coherent avec le PnL simule."
                if ok
                else "Incoherence detectee: verifier historique, positions ouvertes et logs avant interpretation."
            ),
        }

    def build_decision_log_pnl_summary() -> dict[str, Any]:
        log_dir = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
        cache_path = log_dir / SUMMARY_CACHE_FILE
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
                top_reasons = payload.get("top_refusal_reasons") or []
                return {
                    "source_dir": str(log_dir),
                    "events": int(payload.get("event_count") or 0),
                    "accepted": int(payload.get("accepted_count") or 0),
                    "refused": int(payload.get("refused_count") or 0),
                    "positive_events": int(payload.get("positive_count") or 0),
                    "negative_events": int(payload.get("negative_count") or 0),
                    "closed_log_event_pnl_usdc": safe_float(payload.get("total_estimated_pnl_usdc"), 0.0),
                    "fees_usdc": safe_float(payload.get("total_fees_usdc"), 0.0),
                    "top_refusal_reasons": [
                        {"reason": str(item[0]), "count": int(item[1])}
                        for item in top_reasons[:8]
                        if isinstance(item, list | tuple) and len(item) >= 2
                    ],
                    "scope": "complete local decision log cache, separate from fresh launcher session balance",
                    "summary_cache_used": True,
                    "summary_cache_path": str(cache_path),
                    "summary_cache_updated_at": int(cache_path.stat().st_mtime),
                    "read_only": True,
                    "execution": "forbidden",
                }
            except (OSError, json.JSONDecodeError, TypeError, ValueError, IndexError):
                pass
        analysis = analyze_decision_logs_summary(log_dir)
        return {
            "source_dir": str(log_dir),
            "events": analysis.event_count,
            "accepted": analysis.accepted_count,
            "refused": analysis.refused_count,
            "positive_events": analysis.positive_count,
            "negative_events": analysis.negative_count,
            "closed_log_event_pnl_usdc": analysis.total_estimated_pnl_usdc,
            "fees_usdc": analysis.total_fees_usdc,
            "top_refusal_reasons": [
                {"reason": reason, "count": count}
                for reason, count in analysis.top_refusal_reasons[:8]
            ],
            "scope": "complete local decision log, separate from fresh launcher session balance",
            "summary_cache_used": False,
            "read_only": True,
            "execution": "forbidden",
        }

    def build_loss_diagnostics(
        events: list[dict[str, Any]],
        *,
        equity: dict[str, Any],
        reasons: Counter[str],
    ) -> dict[str, Any]:
        loss_by_coin: dict[str, float] = defaultdict(float)
        gain_by_coin: dict[str, float] = defaultdict(float)
        loss_by_wallet: dict[str, float] = defaultdict(float)
        reason_counts: Counter[str] = Counter()
        stale_events = 0
        priced_events = 0
        negative_events = 0
        positive_events = 0
        total_event_pnl = 0.0
        for row in events:
            reason_text = str(row.get("reason") or "")
            if reason_text:
                for reason in reason_text.split("|"):
                    if reason:
                        reason_counts[reason] += 1
                        if reason == "STALE_SIGNAL":
                            stale_events += 1
            signal_age = row.get("signal_age_ms")
            if signal_age is not None:
                priced_events += 1
            pnl = row.get("estimated_net_pnl_usdc")
            if pnl is None:
                continue
            pnl_value = safe_float(pnl, 0.0)
            total_event_pnl += pnl_value
            coin = str(row.get("coin") or "UNKNOWN")
            wallet = str(row.get("wallet_address") or "UNKNOWN")
            if pnl_value < 0:
                negative_events += 1
                loss_by_coin[coin] += pnl_value
                loss_by_wallet[wallet] += pnl_value
            elif pnl_value > 0:
                positive_events += 1
                gain_by_coin[coin] += pnl_value
        stale_ratio = (stale_events / max(1, priced_events)) if priced_events else 0.0
        current_pnl = safe_float(equity.get("current_pnl_usdc"), 0.0)
        costs = safe_float(equity.get("bot_costs_paid_usdc"), 0.0)
        open_exposure = safe_float(equity.get("open_exposure_usdt"), 0.0)
        recommendations: list[str] = []
        if current_pnl < 0:
            recommendations.append(
                "Ne pas augmenter la taille: le PnL courant est negatif; priorite aux filtres fraicheur, consensus et couts."
            )
        if stale_ratio > 0.25 or reasons.get("STALE_SIGNAL"):
            recommendations.append(
                "Les entrees arrivent trop tard: consensus tres chaud vise 4 secondes, simulation autorisee seulement jusqu'a la fenetre fraiche configuree."
            )
        if costs > 0 and current_pnl < 0 and costs >= abs(current_pnl) * 0.35:
            recommendations.append("Les couts pèsent lourd: refuser les edges faibles et les coins avec spread/slippage defavorables.")
        if loss_by_coin:
            worst_coin = min(loss_by_coin.items(), key=lambda item: item[1])
            recommendations.append(f"Mettre {worst_coin[0]} en pause locale si la perte session continue ({worst_coin[1]:.4f} USDC).")
        if open_exposure > safe_float(equity.get("current_equity_usdt"), 1000.0) * 0.5:
            recommendations.append("Exposition elevee: reduire le nombre de positions simultanees ou le notional par entree.")
        if not recommendations:
            recommendations.append("Aucune cause dominante: continuer a collecter des deltas frais et verifier le consensus multi-wallet.")
        try:
            from hl_observer.ui.v12_panels import build_no_trade_panel as _build_nt_panel
            _no_trade_explorer = _build_nt_panel(reasons)
        except Exception:
            _no_trade_explorer = None
        try:
            from hl_observer.sources.shared_recorder import get_shared_recorder as _gsr
            from hl_observer.ui.v12_panels import build_source_health_panel as _bshp
            _source_health = _bshp(_gsr())
        except Exception:
            _source_health = None
        try:
            from hl_observer.evidence.no_trade_evidence import no_trade_evidence_row as _ntev
            _no_trade_evidence = []
            for _code, _cnt in reasons.most_common(12):
                try:
                    _no_trade_evidence.append({**_ntev(_code), "count": _cnt})
                except Exception:
                    pass
        except Exception:
            _no_trade_evidence = None
        return {
            "current_session_pnl_usdc": round(current_pnl, 6),
            "total_event_pnl_usdc": round(total_event_pnl, 6),
            "negative_events": negative_events,
            "positive_events": positive_events,
            "stale_ratio": round(stale_ratio, 6),
            "costs_paid_usdc": round(costs, 6),
            "top_loss_reasons": [{"reason": key, "count": value} for key, value in reason_counts.most_common(12)],
            "top_no_trade_reasons": [{"reason": key, "count": value} for key, value in reasons.most_common(12)],
            "no_trade_explorer": _no_trade_explorer,
            "source_health": _source_health,
            "no_trade_evidence": _no_trade_evidence,
            "losing_coins": [
                {"coin": coin, "pnl_usdc": round(value, 6)}
                for coin, value in sorted(loss_by_coin.items(), key=lambda item: item[1])[:12]
            ],
            "winning_coins": [
                {"coin": coin, "pnl_usdc": round(value, 6)}
                for coin, value in sorted(gain_by_coin.items(), key=lambda item: item[1], reverse=True)[:12]
            ],
            "losing_wallets": [
                {"wallet_address": wallet, "pnl_usdc": round(value, 6)}
                for wallet, value in sorted(loss_by_wallet.items(), key=lambda item: item[1])[:12]
            ],
            "recommendations": recommendations,
            "research_only": True,
            "profit_guarantee": False,
            "execution": "forbidden",
        }

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
            leader_rows = session.scalars(
                select(TopWallet)
                .where(or_(TopWallet.status.is_(None), TopWallet.status != "rejected"))
                .order_by(TopWallet.score.desc(), TopWallet.selected_at_ms.desc())
                .limit(max(settings.copy_trading.top_leaders * 4, 200))
            ).all()
            leaders = [row.wallet_address for row in unique_top_wallets(leader_rows, limit=settings.copy_trading.top_leaders)]
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

    @router.get("/api/v12/panels")
    async def v12_panels(limit: int = 200) -> dict[str, Any]:
        """Read-only V12 panels: Source Health + NO_TRADE Explorer + Decision Funnel.

        Aggregates ONLY real recorded values (recorder health, rejected/follow decisions).
        Pure read-only: never an order, never fabricates, honest empty state.
        """
        from collections import namedtuple

        limit = max(1, min(limit, 500))
        reasons: Counter[str] = Counter()
        _Dec = namedtuple("_Dec", ["accepted", "reason_code"])
        decisions: list[Any] = []
        try:
            with session_factory() as session:
                rejected = session.scalars(
                    select(RejectedSignal).order_by(RejectedSignal.created_at.desc()).limit(limit)
                ).all()
                follow = session.scalars(
                    select(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)
                ).all()
            for row in rejected:
                reasons[str(row.reason or row.decision or "rejected_signal")] += 1
            for row in follow:
                allowed = bool(getattr(row, "allowed", False))
                row_reasons = list(row.reasons_json or []) if not allowed else []
                code = (
                    str(row_reasons[0]) if row_reasons
                    else (None if allowed else str(row.decision or "follow_decision_rejected"))
                )
                decisions.append(_Dec(accepted=allowed, reason_code=code))
                for reason in row_reasons:
                    reasons[str(reason)] += 1
        except Exception:
            pass
        recorder = None
        try:
            from hl_observer.sources.shared_recorder import get_shared_recorder
            recorder = get_shared_recorder()
        except Exception:
            recorder = None
        now_ms = int(__import__("time").time() * 1000)
        try:
            from hl_observer.ui.v12_panels import build_v12_panels
            panels = build_v12_panels(
                recorder=recorder, reason_counts=reasons, decisions=decisions, now_ms=now_ms
            )
        except Exception as exc:  # pragma: no cover - defensive
            panels = {
                "error": str(exc),
                "source_health": None,
                "no_trade_explorer": None,
                "decision_funnel": None,
                "generated_at_ms": now_ms,
            }
        try:
            from hl_observer.ui.v12_extended_panels import build_extended_panels
            panels["extended"] = build_extended_panels()  # honest empty until live feeds attach
        except Exception:
            panels["extended"] = None
        try:
            from hl_observer.ml.inference import get_model
            from hl_observer.ml.model_panel import build_model_panel
            import os as _os
            _model_path = _os.environ.get("HYPERSMART_V13_MODEL_PATH") or "runtime/models/trade_model_v13.json"
            _report_path = _os.environ.get("HYPERSMART_V13_MODEL_REPORT") or (_model_path + ".report.json")
            panels["model"] = build_model_panel(
                get_model(),
                report_path=_report_path,
            )   # #149 read-only AI model status
        except Exception:
            panels["model"] = None
        try:
            from hl_observer.calibration.ledger_calibration_report import build_ledger_calibration_report
            _preds = []
            try:
                import os as _os
                from hl_observer.ml.inference import get_model as _gm
                from hl_observer.ml.ledger_extract import rows_outcomes_from_samples as _ros
                _m = _gm()
                if _m is not None:
                    _rows, _outs = _ros(_os.environ.get("HYPERSMART_V13_SAMPLES_PATH")
                                        or "runtime/ml/training_samples.jsonl")
                    _by = {o.decision_id: o for o in _outs}
                    for _r in _rows:
                        _o = _by.get(_r.decision_id)
                        if _o is not None:
                            _preds.append((_m.predict_proba_one(_r.features),
                                           1 if float(_o.realized_net_pnl_usdc) > 0 else 0))
            except Exception:
                _preds = []
            panels["calibration"] = build_ledger_calibration_report(predictions=_preds, block_reasons=reasons)  # #157
        except Exception:
            panels["calibration"] = None
        # #156 explanations: read the cache written by the background explain loop (Ollama when
        # enabled), instant. Fallback: rule-based per NO_TRADE reason. NEVER calls Ollama here
        # (no UI blocking).
        try:
            import json as _json
            import os as _os
            _cache = _os.environ.get("HYPERSMART_V13_EXPL_PATH") or "runtime/ml/explanations_latest.json"
            if _os.path.exists(_cache):
                panels["explanations"] = _json.loads(open(_cache, encoding="utf-8").read())
            else:
                from hl_observer.research.local_llm_explainer import explain as _ex
                _nt = panels.get("no_trade_explorer") or {}
                _items = [{"coin": "", "side": "", "reason": _c.get("reason_code"),
                           "text": _ex({"reason": _c.get("reason_code")}, use_llm=False)["text"],
                           "source": "regles"}
                          for _c in (_nt.get("by_code") or [])[:6]]
                panels["explanations"] = {"items": _items, "ollama_narrative": None, "ollama_enabled": False}
        except Exception:
            panels["explanations"] = None
        # #158 risk panel: real recent trade PnLs (training_samples) + open positions/equity
        # (live snapshot). Read-only, guarded, instant.
        try:
            import glob as _glob
            import json as _rj
            import os as _ro
            from hl_observer.risk.risk_panel import build_risk_panel
            _pnls = []
            _sp = _ro.environ.get("HYPERSMART_V13_SAMPLES_PATH") or "runtime/ml/training_samples.jsonl"
            if _ro.path.exists(_sp):
                for _ln in open(_sp, encoding="utf-8"):
                    _ln = _ln.strip()
                    if _ln:
                        try:
                            _pnls.append(float(_rj.loads(_ln).get("net_pnl_usdc", 0.0)))
                        except Exception:
                            pass
            _pos, _eq = [], None
            _snaps = _glob.glob("logs/**/simulation_snapshot_latest.json", recursive=True)
            if _snaps:
                try:
                    _snap = _rj.loads(open(max(_snaps, key=_ro.path.getmtime), encoding="utf-8").read())
                    _bs = _snap.get("bot_simulation") or {}
                    _eq = _bs.get("current_equity_usdt")
                    for _p in (_bs.get("open_positions") or []):
                        _pos.append({"side": _p.get("direction") or _p.get("side"),
                                     "notional_usdt": _p.get("open_exposure_usdt") or _p.get("notional_usdt") or 0.0})
                except Exception:
                    pass
            panels["risk"] = build_risk_panel(recent_trade_pnls=_pnls[-200:], open_positions=_pos, equity=_eq)
        except Exception:
            panels["risk"] = None
        # #166 freshness panel: per-stage latency + age histogram from the local decision logs.
        try:
            from hl_observer.realtime.freshness_audit import build_freshness_audit_from_logs
            from hl_observer.runtime.session_logs import default_logs_to_send_dir as _ld
            _fa = build_freshness_audit_from_logs(_ld(), stale_threshold_ms=15_000)
            panels["freshness"] = {
                "status": _fa.status,
                "samples": _fa.samples,
                "fresh_ratio": _fa.histogram.fresh_ratio,
                "stale_ratio": _fa.histogram.stale_ratio,
                "histogram": [{"label": b.label, "count": b.count} for b in _fa.histogram.buckets],
                "stages": [
                    {"name": s.name, "samples": s.samples, "p50_ms": s.p50_ms, "p95_ms": s.p95_ms, "max_ms": s.max_ms}
                    for s in _fa.stages
                ],
            }
        except Exception:
            panels["freshness"] = None
        panels["research_only"] = True
        panels["execution"] = "forbidden"
        return panels

    @router.get("/metrics")
    def observability_metrics() -> Any:
        """#208 — read-only observability (Prometheus text): open positions + lag/throughput.
        No action, no order; counters default to 0 until wired to the live loop."""
        from fastapi.responses import PlainTextResponse
        from hl_observer.realtime.metrics_endpoint import build_metrics, format_metrics_prometheus
        import glob as _g, json as _j, os as _o
        _pos = 0
        try:
            _snaps = _g.glob("logs/**/simulation_snapshot_latest.json", recursive=True)
            if _snaps:
                _snap = _j.loads(open(max(_snaps, key=_o.path.getmtime), encoding="utf-8").read())
                _bs = _snap.get("bot_simulation") or {}
                _pos = len(_bs.get("open_positions") or [])
        except Exception:
            _pos = 0
        m = build_metrics(open_positions=_pos)
        return PlainTextResponse(format_metrics_prometheus(m))

    @router.get("/api/simulation/overview")
    def simulation_overview(limit: int = 500) -> dict[str, Any]:
        limit = max(1, min(limit, 2_000))
        # Keep display bounded by `limit`, but always analyze a much wider
        # fresh slice. In live runs the latest rows can be reduce/close noise,
        # while the exploitable same-coin/same-side entry cluster sits a few
        # hundred or thousand rows back. Tying analysis depth to UI display
        # made the dashboard miss opportunities that the CLI scanner found.
        analysis_delta_limit = max(5_000, min(20_000, limit * 25))
        simulation_started_at_ms = state.simulation_started_at_ms
        current_time_ms = now_ms()
        cached_payload = simulation_overview_cache.get("payload")
        cached_at_ms = int(simulation_overview_cache.get("computed_at_ms") or 0)
        cached_limit = simulation_overview_cache.get("limit")
        if (
            limit >= 50
            and cached_limit == limit
            and isinstance(cached_payload, dict)
            and current_time_ms - cached_at_ms < 3_000
        ):
            payload_copy = dict(cached_payload)
            payload_copy["overview_cache_hit"] = True
            payload_copy["overview_cache_age_ms"] = current_time_ms - cached_at_ms
            payload_copy["current_time_ms"] = current_time_ms
            return payload_copy
        with session_factory() as session:
            leader_rows = session.scalars(select(TopWallet).order_by(TopWallet.score.desc()).limit(250)).all()
            leaderboard_candidate_rows = session.scalars(
                select(LeaderboardWalletCandidate).order_by(LeaderboardWalletCandidate.leaderboard_score.desc()).limit(500)
            ).all()
            max_signal_age_ms = simulation_max_signal_age_ms()
            entry_analysis_cutoff_ms = max(simulation_started_at_ms, current_time_ms - max_signal_age_ms)
            exit_analysis_cutoff_ms = max(simulation_started_at_ms, current_time_ms - max_signal_age_ms * 10)
            recent_delta_condition = or_(
                PositionDeltaModel.exchange_ts >= exit_analysis_cutoff_ms,
                PositionDeltaModel.detected_at_ms >= exit_analysis_cutoff_ms,
            )
            fresh_entry_condition = or_(
                PositionDeltaModel.exchange_ts >= entry_analysis_cutoff_ms,
                PositionDeltaModel.detected_at_ms >= entry_analysis_cutoff_ms,
            )
            fresh_delta_query = (
                select(PositionDeltaModel)
                .where(recent_delta_condition)
                .order_by(PositionDeltaModel.detected_at_ms.desc())
                .limit(analysis_delta_limit)
            )
            latest_deltas = session.scalars(fresh_delta_query).all()
            fresh_entry_query = (
                select(PositionDeltaModel)
                .where(
                    fresh_entry_condition,
                    PositionDeltaModel.delta_type.in_(("open_long", "open_short", "add_long", "add_short", "increase_long", "increase_short")),
                )
                .order_by(PositionDeltaModel.detected_at_ms.desc())
                .limit(analysis_delta_limit)
            )
            fresh_entry_deltas = session.scalars(fresh_entry_query).all()
            delta_by_key: dict[str, PositionDeltaModel] = {}
            for row in [*latest_deltas, *fresh_entry_deltas]:
                key = row.delta_hash or f"id:{row.id}" or f"{row.wallet_address}:{row.coin}:{row.detected_at_ms}:{row.delta_type}"
                delta_by_key[str(key)] = row
            deltas = sorted(
                delta_by_key.values(),
                key=lambda row: int(row.detected_at_ms or row.exchange_ts or 0),
                reverse=True,
            )[: max(analysis_delta_limit * 2, limit)]
            decisions = session.scalars(select(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(limit)).all()
            paper_orders = session.scalars(select(PaperFollowOrder).order_by(PaperFollowOrder.created_at_ms.desc()).limit(limit)).all()
            pnl_fills = session.scalars(select(Fill).where(Fill.closed_pnl.is_not(None)).order_by(Fill.exchange_ts.asc()).limit(500)).all()
            latest_market_snapshots = session.scalars(
                select(MarketSnapshot).order_by(desc(MarketSnapshot.id)).limit(50)
            ).all()
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
                    select(func.count(func.distinct(TopWallet.wallet_address))).where(TopWallet.source == "public_trades_ws")
                )
                or 0
            )
            # Health coverage is not the same as the copy-entry freshness gate.
            # A full scan cycle can take longer than the 4s entry window, so a
            # 20s health window made the UI report "no fresh market prices"
            # immediately after a valid read-only scan. Entry scoring below
            # still uses the strict signal-age gate.
            fresh_coverage_window_ms = max(90_000, simulation_max_signal_age_ms())
            warehouse_report = build_warehouse_coverage_report(
                session,
                now_ms=current_time_ms,
                fresh_window_ms=fresh_coverage_window_ms,
            )
            fills_count = fast_table_count(session, Fill)
            positions_count = fast_table_count(session, Position)
            open_orders_count = fast_table_count(session, OpenOrder)
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
        mid_prices, mid_price_sources = latest_mark_prices_from_snapshots(list(latest_market_snapshots))
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

        def row_copy_signal_time_ms(row: PositionDeltaModel) -> int:
            return copy_candidate_signal_time_ms(row)

        live_simulation_deltas = [
            row
            for row in deltas
            if delta_event_time_ms(row) >= exit_analysis_cutoff_ms
        ]
        old_deltas_ignored = max(0, len(deltas) - len(live_simulation_deltas))
        last_live_event_ms = max((delta_event_time_ms(row) for row in live_simulation_deltas), default=None)
        seconds_since_last_live_event = (
            max(0, int((current_time_ms - last_live_event_ms) / 1000))
            if last_live_event_ms is not None
            else None
        )
        max_live_signal_age_seconds = max(1, int(simulation_max_signal_age_ms() / 1000))
        live_data_stale = (
            seconds_since_last_live_event is not None
            and seconds_since_last_live_event > max_live_signal_age_seconds
        )

        entry_deltas = []
        ignored_deltas = 0
        stale_entry_deltas_count = 0

        for row in live_simulation_deltas:
            action = copy_delta_action(row)
            direction = copy_delta_direction(row, action)
            if action in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"} and direction is not None:
                leader_event_at = row_copy_signal_time_ms(row)
                if leader_event_at and current_time_ms - leader_event_at > max_live_signal_age_seconds * 1000:
                    stale_entry_deltas_count += 1
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
        if live_data_stale:
            reasons["LIVE_DATA_STALE_WAITING_FOR_NEW_EVENTS"] += 1

        consensus_window_ms = 4_000
        consensus = build_position_consensus(live_simulation_deltas, window_ms=consensus_window_ms, min_wallets=2)
        existing_virtual_positions = state.simulation_virtual_positions or {}
        existing_open_exposure_usdt = 0.0
        for raw_position in existing_virtual_positions.values():
            if not isinstance(raw_position, dict):
                continue
            existing_open_exposure_usdt += abs(
                safe_float(raw_position.get("size"), 0.0)
                * safe_float(raw_position.get("avg_price"), 0.0)
            )
        fresh_opportunity_risk_config = RealtimeCopyRiskConfig(
            min_edge_required_bps=max(
                1.0,
                calibrated_float_env("HYPERSMART_SIMULATION_MIN_EDGE_BPS", DEFAULT_SIMULATION_MIN_EDGE_BPS),
            ),
            fee_bps=4.0,
            spread_bps=3.0,
            slippage_bps=5.0,
            max_signal_age_ms=simulation_max_signal_age_ms(),
            min_liquidity_score=calibrated_float_env(
                "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE",
                DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE,
            ),
            max_copy_degradation_bps=safe_float(
                os.environ.get("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS"),
                DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS,
            ),
            max_price_deviation_bps=safe_float(
                os.environ.get("HYPERSMART_SIMULATION_MAX_PRICE_DEVIATION_BPS"),
                8.0,
            ),
            starting_equity_usdt=state.simulation_starting_equity_usdt,
            max_position_notional_usdt=safe_float(
                os.environ.get("HYPERSMART_MAX_POSITION_USDT"),
                max(50.0, state.simulation_starting_equity_usdt * 0.10),  # 10%% du capital, min 50
            ),
            max_total_exposure_usdt=safe_float(
                os.environ.get("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT"),
                max(400.0, state.simulation_starting_equity_usdt * 0.80),  # 80%% du capital deployable
            ),
            single_wallet_min_edge_required_bps=safe_float(
                os.environ.get("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS"),
                DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS,
            ),
        )
        fresh_opportunity_report = find_fresh_opportunities(
            live_simulation_deltas,
            leaders,
            now_timestamp_ms=current_time_ms,
            current_mids=mid_prices,
            active_window_ms=simulation_max_signal_age_ms(),
            consensus_window_ms=consensus_window_ms,
            min_wallets=2,
            max_opportunities=25,
            current_open_exposure_usdt=existing_open_exposure_usdt,
            current_open_positions=len(existing_virtual_positions),
            max_open_positions=int(safe_float(os.environ.get("HYPERSMART_MAX_OPEN_POSITIONS"), 6)),
            risk_config=fresh_opportunity_risk_config,
        )
        accepted_opportunity_deltas = build_consensus_replay_deltas(
            list(fresh_opportunity_report.opportunities),
            live_simulation_deltas,
            allow_add_as_entry=calibrated_bool_env(
                "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY",
                DEFAULT_SIMULATION_ALLOW_ADD_AS_ENTRY,
            ),
            processed_delta_keys=state.simulation_processed_delta_keys,
        )
        simulation_replay_deltas = [*accepted_opportunity_deltas, *live_simulation_deltas]
        bot_simulation = build_bot_simulation(
            simulation_replay_deltas,
            mid_prices=mid_prices,
            max_events=limit,
            now_timestamp_ms=current_time_ms,
            starting_equity_usdt=state.simulation_starting_equity_usdt,
            existing_positions=state.simulation_virtual_positions,
            existing_events=state.simulation_ledger_events,
            processed_delta_keys=state.simulation_processed_delta_keys,
            existing_realized_pnl_usdc=state.simulation_realized_pnl_usdc,
            existing_entry_costs_paid_usdc=state.simulation_entry_costs_paid_usdc,
            existing_exit_costs_paid_usdc=state.simulation_exit_costs_paid_usdc,
            existing_reproduced_entries_total=state.simulation_reproduced_entries_total,
            existing_reproduced_exits_total=state.simulation_reproduced_exits_total,
        )
        state.simulation_virtual_positions = bot_simulation["virtual_positions_state"]
        state.simulation_ledger_events = bot_simulation["ledger_events"]
        state.simulation_processed_delta_keys = set(bot_simulation["processed_delta_keys"])
        state.simulation_realized_pnl_usdc = float(bot_simulation["realized_net_pnl_usdc"])
        state.simulation_entry_costs_paid_usdc = float(bot_simulation["entry_costs_paid_usdc"])
        state.simulation_exit_costs_paid_usdc = float(bot_simulation["exit_costs_paid_usdc"])
        state.simulation_reproduced_entries_total = int(bot_simulation["reproduced_entries"])
        state.simulation_reproduced_exits_total = int(bot_simulation["reproduced_exits"])
        append_simulation_equity_history(bot_simulation, current_time_ms)
        persist_simulation_state_safe("simulation_overview_refresh")
        for event in bot_simulation["events"]:
            if event.get("status") == "REFUSED" and event.get("reason"):
                for reason in str(event["reason"]).split("|"):
                    if reason:
                        reasons[reason] += 1
        for reason, count in fresh_opportunity_report.rejection_reasons:
            reasons[f"OPPORTUNITY_{reason}"] += count
        stale_signal_refusals = sum(
            1
            for event in bot_simulation["events"]
            if event.get("status") == "REFUSED" and "STALE_SIGNAL" in str(event.get("reason") or "")
        )
        stale_entry_signals_only = bool(
            entry_deltas
            and stale_signal_refusals >= len(entry_deltas)
            and bot_simulation["reproduced_entries"] == 0
        )
        live_data_stale = live_data_stale or stale_entry_signals_only
        if entry_deltas and stale_entry_deltas_count >= len(entry_deltas) and bot_simulation["reproduced_entries"] == 0:
            live_data_stale = True
        if stale_entry_signals_only:
            reasons["ALL_ENTRY_SIGNALS_TOO_OLD_FOR_COPY"] += 1
        if live_data_stale and stale_entry_deltas_count:
            reasons["ENTRY_DELTAS_TOO_OLD_FOR_COPY"] += stale_entry_deltas_count
        for bottleneck in warehouse_report.bottlenecks:
            reasons[f"FRESH_DATA_{bottleneck}"] += 1
        equity_candles = build_session_equity_candles(state.simulation_equity_history)
        bot_candles = equity_candles
        equity_close = equity_candles[-1]["equity_close"] if equity_candles else 0.0
        equity_high = max((row["ha_high"] for row in equity_candles), default=0.0)
        equity_low = min((row["ha_low"] for row in equity_candles), default=0.0)
        simulation_poll_interval_seconds = safe_int_env("HYPERSMART_SIMULATION_INTERVAL_SECONDS") or min(
            settings.copy_trading.default_interval_seconds,
            60,
        )
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
        elif live_data_stale:
            readiness = "LIVE_DATA_STALE_WAITING_FOR_NEW_EVENTS"
            next_step = (
                "Le scanner n'a pas produit de delta leader exploitable depuis plus d'une minute. "
                "Le bot ne doit pas ouvrir de nouvelle position sur ces donnees perimees; relancer le lanceur/poller read-only si besoin."
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

        fresh_diag = bot_simulation.get("fresh_entry_diagnostics") or {}
        filter_diag = bot_simulation.get("filter_diagnostics") or {}
        admission_candidates = int(fresh_diag.get("admission_candidates_seen") or 0)
        fresh_entries_seen = int(fresh_diag.get("admission_fresh_entries_seen") or 0)
        accepted_entries_this_cycle = int(bot_simulation.get("new_reproduced_entries") or 0)
        refused_entries_this_cycle = sum(
            1
            for row in bot_simulation.get("new_ledger_events") or []
            if row.get("status") == "REFUSED"
            and str(row.get("leader_action") or "").upper() in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
        )
        if admission_candidates <= 0:
            entry_supply_bottleneck = "NO_DATA"
            entry_supply_summary = "Aucun candidat frais dans ce cycle: collecte/WS/shortlist a verifier."
        elif accepted_entries_this_cycle > 0:
            entry_supply_bottleneck = "OK"
            entry_supply_summary = "Au moins une entree paper locale a ete acceptee sur donnees fraiches."
        elif fresh_entries_seen <= 0:
            entry_supply_bottleneck = "SUPPLY"
            entry_supply_summary = "Offre insuffisante: les deltas vus sont anciens, orphelins ou non simulables."
        else:
            entry_supply_bottleneck = "GATES"
            entry_supply_summary = "Des entrees fraiches existent, mais edge/liquidite/couts/risque les refusent."
        entry_supply_payload = {
            "bottleneck": entry_supply_bottleneck,
            "summary": entry_supply_summary,
            "candidates": admission_candidates,
            "fresh_entries": fresh_entries_seen,
            "accepted_entries": accepted_entries_this_cycle,
            "refused_entries": refused_entries_this_cycle,
            "prefilter_skips": int(bot_simulation.get("prefilter_skip_count") or 0),
            "skip_reasons": dict(sorted(filter_diag.items(), key=lambda item: int(item[1]), reverse=True)[:12]),
            "next_action": (
                "Augmenter la collecte read-only de donnees fraiches et verifier les timestamps."
                if entry_supply_bottleneck in {"NO_DATA", "SUPPLY"}
                else "Analyser edge_remaining_bps, spread, slippage, liquidite et consensus avant de modifier les seuils."
                if entry_supply_bottleneck == "GATES"
                else "Continuer a mesurer PnL/equity/drawdown en paper local."
            ),
            "read_only": True,
            "execution": "forbidden",
        }

        equity_payload = {
            "current_pnl_usdc": bot_simulation["estimated_net_pnl_usdc"] if bot_candles else round(float(equity_close), 6),
            "starting_equity_usdt": state.simulation_starting_equity_usdt,
            "current_equity_usdt": bot_simulation["current_equity_usdt"],
            "free_equity_usdt": bot_simulation["free_equity_usdt"],
            "open_exposure_usdt": bot_simulation["open_exposure_usdt"],
            "open_exposure_pct": bot_simulation["open_exposure_pct"],
            "realized_pnl_usdc": bot_simulation["realized_net_pnl_usdc"],
            "unrealized_pnl_usdc": bot_simulation["unrealized_pnl_usdc"],
            "high_pnl_usdc": round(float(equity_high), 6),
            "low_pnl_usdc": round(float(equity_low), 6),
            "candles_count": len(equity_candles),
            "source": "fresh bot virtual portfolio simulation from deltas detected after simulation start",
            "bot_net_pnl_usdc": bot_simulation["estimated_net_pnl_usdc"],
            "bot_cost_model_bps": bot_simulation["cost_model_bps"],
            "bot_costs_paid_usdc": bot_simulation["total_costs_paid_usdc"],
            "market_marks_available": len(mid_prices),
            "market_mark_sources": sorted(set(mid_price_sources.values())),
        }
        decision_log_pnl = build_decision_log_pnl_summary()
        equity_payload["decision_log_total_pnl_usdc"] = decision_log_pnl["closed_log_event_pnl_usdc"]
        equity_payload["decision_log_events"] = decision_log_pnl["events"]
        pnl_consistency = build_pnl_consistency(equity_payload)
        pnl_consistency["scope_note"] = (
            "Gain/perte session = simulation fraiche depuis le lanceur. "
            "Journal decisions = tous les evenements locaux historiques; les deux scopes ne doivent pas etre additionnes."
        )
        pnl_consistency["decision_log_total_pnl_usdc"] = decision_log_pnl["closed_log_event_pnl_usdc"]
        loss_diagnostics = build_loss_diagnostics(
            bot_simulation["ledger_events"],
            equity=equity_payload,
            reasons=reasons,
        )
        fresh_data_coverage = {
            "readiness": warehouse_report.readiness,
            "fresh_window_seconds": int(warehouse_report.fresh_window_ms / 1000),
            "wallet_candidates_total": warehouse_report.wallet_candidates_total,
            "public_trade_candidates": warehouse_report.public_trade_candidates,
            "selected_top_wallets": warehouse_report.selected_top_wallets,
            "fresh_top_wallets": warehouse_report.fresh_top_wallets,
            "stale_top_wallets": warehouse_report.stale_top_wallets,
            "wallet_snapshots_total": warehouse_report.wallet_snapshots_total,
            "fresh_wallet_snapshots": warehouse_report.fresh_wallet_snapshots,
            "public_trade_events": warehouse_report.public_trade_events,
            "fresh_public_trade_events": warehouse_report.fresh_public_trade_events,
            "market_snapshots_total": warehouse_report.market_snapshots_total,
            "fresh_market_snapshots": warehouse_report.fresh_market_snapshots,
            "position_deltas_total": warehouse_report.position_deltas_total,
            "fresh_position_deltas": warehouse_report.fresh_position_deltas,
            "fresh_entry_deltas": warehouse_report.fresh_entry_deltas,
            "follow_signals_total": warehouse_report.follow_signals_total,
            "fresh_follow_signals": warehouse_report.fresh_follow_signals,
            "accepted_follow_decisions": warehouse_report.accepted_follow_decisions,
            "rejected_follow_decisions": warehouse_report.rejected_follow_decisions,
            "paper_follow_orders_total": warehouse_report.paper_follow_orders_total,
            "risk_events_total": warehouse_report.risk_events_total,
            "sources_total": warehouse_report.sources_total,
            "unhealthy_sources": warehouse_report.unhealthy_sources,
            "bottlenecks": list(warehouse_report.bottlenecks),
            "next_actions": list(warehouse_report.next_actions),
            "read_only": True,
            "execution": "forbidden",
            "real_orders_created": 0,
            "profit_guarantee": False,
        }

        payload = {
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
            "entry_analysis_cutoff_ms": entry_analysis_cutoff_ms,
            "exit_analysis_cutoff_ms": exit_analysis_cutoff_ms,
            "simulation_state_persistent": True,
            "simulation_state_path": str(simulation_state_path(settings)),
            "simulation_ledger_events_count": len(state.simulation_ledger_events),
            "simulation_processed_deltas_count": len(state.simulation_processed_delta_keys),
            "simulation_equity_history_count": len(state.simulation_equity_history),
            "current_time_ms": current_time_ms,
            "last_live_event_ms": last_live_event_ms,
            "seconds_since_last_live_event": seconds_since_last_live_event,
            "live_data_stale": live_data_stale,
            "max_live_signal_age_seconds": max_live_signal_age_seconds,
            "stale_entry_deltas_count": stale_entry_deltas_count,
            "beginner_status": {
                "simple_state": (
                    "Flux live perime: le bot attend une nouvelle ouverture fraiche."
                    if live_data_stale
                    else "Flux live pret: le bot peut analyser les nouveaux deltas."
                ),
                "pnl_explanation": (
                    "Le solde ne doit bouger que sur une entree/sortie virtuelle acceptee ou sur la mise a jour du prix d'une position ouverte."
                ),
                "decision_policy": (
                    "Le bot refuse les donnees anciennes, les ADD sans ouverture originale, les signaux sans edge restant et les positions sans consensus suffisant."
                ),
            },
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
                "market_marks_available": len(mid_prices),
                "market_mark_sources": sorted(set(mid_price_sources.values())),
                "network_read_required_for_live_updates": True,
                "fresh_only": True,
                "old_history_ignored_for_pnl": True,
                "fresh_consensus_window_seconds": int(consensus_window_ms / 1000),
                "entry_supply": entry_supply_payload,
                "entry_supply_summary": entry_supply_summary,
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
                "fresh_opportunity_groups": fresh_opportunity_report.groups_seen,
                "fresh_opportunities_accepted": fresh_opportunity_report.accepted_for_simulation,
                "fresh_opportunity_replay_deltas": len(accepted_opportunity_deltas),
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
            "signal_pipeline": {
                "wallets_seen_from_public_ws": public_trade_wallets_seen,
                "wallets_promoted_for_info_followup": public_trade_promoted,
                "leaders_loaded_unique": len(leader_cards),
                "leader_deltas_analyzed": len(live_simulation_deltas),
                "entry_deltas_analyzed": len(entry_deltas),
                "fresh_consensus_groups_4s": len(consensus),
                "fresh_opportunity_groups": fresh_opportunity_report.groups_seen,
                "fresh_opportunities_accepted": fresh_opportunity_report.accepted_for_simulation,
                "cluster_opportunities_replayed_locally": len(accepted_opportunity_deltas),
                "local_entries_accepted": bot_simulation["reproduced_entries"],
                "local_exits_replayed": bot_simulation["reproduced_exits"],
                "local_refusals": bot_simulation["refused"],
                "zero_accepted_means": (
                    "Aucun OPEN/ADD frais n'a passe edge_remaining_bps, couts, delai, prix et garde-fous. "
                    "Ce n'est pas zero wallet scanne."
                ),
                "read_only": True,
                "paper_local_only": True,
            },
            "equity": equity_payload,
            "decision_log_pnl": decision_log_pnl,
            "pnl_consistency": pnl_consistency,
            "loss_diagnostics": loss_diagnostics,
            "fresh_data_coverage": fresh_data_coverage,
            "warehouse_coverage": fresh_data_coverage,
            "equity_candles": equity_candles,
            "session_equity_history": state.simulation_equity_history[-240:],
            "bot_simulation": bot_simulation,
            "magic_profile": bot_simulation["magic_profile"],
            "reproduction": bot_simulation,
            "leaders": leader_cards,
            "entry_deltas": entry_deltas[:25],
            "consensus": consensus[:10],
            "fresh_opportunities": [
                {
                    "coin": row.coin,
                    "direction": row.direction,
                    "decision": row.decision,
                    "wallet_count": row.wallet_count,
                    "wallets": list(row.wallets)[:10],
                    "age_ms": row.age_ms,
                    "first_seen_ms": row.first_seen_ms,
                    "last_seen_ms": row.last_seen_ms,
                    "total_notional_usdc": row.total_notional_usdc,
                    "leader_reference_price": row.leader_reference_price,
                    "current_mid": row.current_mid,
                    "edge_remaining_bps": row.edge_remaining_bps,
                    "copy_degradation_bps": row.copy_degradation_bps,
                    "opportunity_score": row.opportunity_score,
                    "risk_score": row.risk_score,
                    "simulated_notional_usdt": row.simulated_notional_usdt,
                    "refusal_reasons": list(row.refusal_reasons),
                    "warnings": list(row.warnings),
                    "research_only": True,
                    "real_order_created": False,
                }
                for row in fresh_opportunity_report.opportunities[:25]
            ],
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
        diagnostic_logs = export_simulation_diagnostics(settings, payload)
        api_bot_simulation = compact_bot_simulation_for_api(bot_simulation)
        payload["bot_simulation"] = api_bot_simulation
        payload["reproduction"] = {
            "same_as": "bot_simulation",
            "api_payload_compacted": True,
            "full_details_location": "logs/logs a envoyer",
        }
        payload["diagnostic_logs"] = diagnostic_logs
        simulation_overview_cache["payload"] = payload
        simulation_overview_cache["computed_at_ms"] = current_time_ms
        simulation_overview_cache["limit"] = limit
        return payload

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
            "title": "dYdX v4 Smart-Wallet Observer",
            "subtitle": (
                "Le logiciel analyse les wallets dYdX v4 via Cosmos LCD + Indexer (REST/WS), "
                "detecte les clusters de wallets vers la meme direction, et genere des signaux paper (0 ordre reel)."
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
            state.simulation_realized_pnl_usdc = 0.0
            state.simulation_entry_costs_paid_usdc = 0.0
            state.simulation_exit_costs_paid_usdc = 0.0
            state.simulation_reproduced_entries_total = 0
            state.simulation_reproduced_exits_total = 0
            state.simulation_equity_history = [initial_simulation_equity_point(state.simulation_started_at_ms)]
            persist_simulation_state_safe("manual_simulation_reset")
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

    router.build_bot_simulation = build_bot_simulation
    return router
