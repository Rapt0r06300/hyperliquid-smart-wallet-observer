"""Fast, read-only `/api/simulation/status` tick endpoint.

Kept in a SMALL separate module (and included from app.py) so it is never added
by editing the very large ui/routes.py, which truncates on edit in this setup.

It returns ONLY the real local paper state (equity / realized PnL / open paper
positions) computed from the in-memory UiState — no DB, no network, NO fabricated
data. The paper simulation is LOCAL, but every position it holds was opened from
REAL Hyperliquid signals upstream. If nothing has traded yet it honestly reports
1000.00 / 0.00 / no positions — it never invents movement.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError

from hl_observer.config.settings import Settings
from hl_observer.signals.entry_supply_diagnostics import (
    BOTTLENECK_GATES,
    BOTTLENECK_NO_DATA,
    BOTTLENECK_OK,
    BOTTLENECK_SUPPLY,
)
from hl_observer.simulation.pnl_reconciliation import reconcile_pnl
from hl_observer.strategies.engine_pnl import rapport_par_moteur as _rapport_par_moteur
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import MarketSnapshot
from hl_observer.strategies.external_github_bridge import build_external_github_bridge_payload
from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.fusion_status_provider import build_fusion_status_payload
from hl_observer.ui.persistent_state import persist_simulation_state, simulation_state_path
from hl_observer.ui.simulation_log_export import export_simulation_diagnostics
from hl_observer.ui.state import UiState
from hl_observer.ui.v12_status_provider import build_v12_status_payload
from hl_observer.utils.time import now_ms
from hl_observer.ops.echec_silencieux import noter as _noter_echec


ENGINE_STATUS_FILENAME = "hypersmart_engine_status.json"
ENGINE_HEARTBEAT_STALE_MS = 45_000
MARK_SNAPSHOT_LIMIT = 60
FAST_STATUS_EXIT_COST_BPS = 12.0
FAST_STATUS_PERSIST_MIN_MS = 900
FAST_STATUS_EXPORT_MIN_MS = int(float(os.getenv("HYPERSMART_STATUS_EXPORT_MIN_MS", "2500")))
LIVE_MARKS_MIN_INTERVAL_MS = int(float(os.getenv("HYPERSMART_STATUS_LIVE_MARKS_MIN_INTERVAL_MS", "1500")))
LIVE_MARKS_MAX_STALE_MS = 5_000
LIVE_MARKS_TIMEOUT_SECONDS = float(os.getenv("HYPERSMART_STATUS_LIVE_MARKS_TIMEOUT_SECONDS", "0.35"))


def create_status_router(state: UiState, settings: Settings | None = None) -> APIRouter:
    router = APIRouter()
    cached_session_factory: Any = None
    live_mark_cache: dict[str, Any] = {
        "fetched_at_ms": 0,
        "prices": {},
        "error": None,
    }
    status_export_cache: dict[str, Any] = {
        "last_export_ms": 0,
        "last_ledger_count": -1,
        "last_result": None,
    }
    live_mark_lock = threading.Lock()

    def latest_market_marks(raw_positions: list[dict[str, Any]], current_ms: int) -> dict[str, Any]:
        live_marks = _live_all_mids_marks(
            settings,
            raw_positions=raw_positions,
            current_ms=current_ms,
            cache=live_mark_cache,
            lock=live_mark_lock,
        )
        if live_marks["prices"]:
            return live_marks
        nonlocal cached_session_factory
        if settings is None:
            return _empty_market_marks("NO_SETTINGS")
        try:
            if cached_session_factory is None:
                cached_session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
            with cached_session_factory() as session:
                snapshots = list(
                    session.scalars(
                        select(MarketSnapshot)
                        .order_by(desc(MarketSnapshot.exchange_ts), desc(MarketSnapshot.id))
                        .limit(MARK_SNAPSHOT_LIMIT)
                    )
                )
        except (OSError, SQLAlchemyError, RuntimeError) as exc:
            return _empty_market_marks("MARKET_SNAPSHOT_READ_FAILED", error=str(exc))
        db_marks = _latest_market_marks_from_snapshots(snapshots)
        if live_marks.get("error"):
            db_marks["live_read_status"] = live_marks.get("read_status")
            db_marks["live_error"] = live_marks.get("error")
        return db_marks

    @router.get("/api/simulation/status")
    def simulation_status() -> dict[str, Any]:
        current_ms = now_ms()
        starting = float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0)
        realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
        raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
        engine_status = _read_engine_status(settings)
        scanner = _scanner_payload_from_engine_status(engine_status, current_ms)
        latest_equity = None
        latest_pnl = None
        history = getattr(state, "simulation_equity_history", None) or []
        if history and isinstance(history[-1], dict):
            latest = history[-1]
            try:
                latest_equity = float(latest.get("current_equity_usdt"))
            except (TypeError, ValueError):
                latest_equity = None
            try:
                latest_pnl = float(latest.get("current_pnl_usdc"))
            except (TypeError, ValueError):
                latest_pnl = None

        market_marks = latest_market_marks(raw_positions, current_ms) if raw_positions else _empty_market_marks("NO_OPEN_POSITION")
        sltp_report = _apply_fast_status_sltp(state, market_marks, current_ms=current_ms)
        if sltp_report["closed_count"]:
            raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
            realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
            market_marks = latest_market_marks(raw_positions, current_ms) if raw_positions else _empty_market_marks("NO_OPEN_POSITION")
        quality_exit_report = _apply_fast_status_quality_exits(state, market_marks, current_ms=current_ms)
        if quality_exit_report["closed_count"]:
            raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
            realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
            market_marks = latest_market_marks(raw_positions, current_ms) if raw_positions else _empty_market_marks("NO_OPEN_POSITION")
        marked = _mark_to_market_positions(
            raw_positions,
            starting_equity_usdt=starting,
            realized_pnl_usdc=realized,
            market_marks=market_marks,
            current_ms=current_ms,
        )
        if marked["marks_used"] > 0:
            equity = float(marked["current_equity_usdt"])
            net_pnl = float(marked["estimated_net_pnl_usdc"])
            _append_fast_equity_point(settings, state, marked, current_ms)
        else:
            equity = round(latest_equity if latest_equity is not None else starting + realized, 6)
            net_pnl = round(latest_pnl if latest_pnl is not None else equity - starting, 6)
            marked["current_equity_usdt"] = equity
            marked["estimated_net_pnl_usdc"] = net_pnl
            marked["realized_pnl_usdc"] = round(realized, 6)
        fusion_status = build_fusion_status_payload(
            state=state,
            engine_status=engine_status,
            scanner=scanner,
            settings=settings,
            current_ms=current_ms,
        )
        fusion_apply_report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=current_ms)
        if fusion_apply_report["applied_count"]:
            raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
            realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
            market_marks = latest_market_marks(raw_positions, current_ms) if raw_positions else _empty_market_marks("NO_OPEN_POSITION")
            marked = _mark_to_market_positions(
                raw_positions,
                starting_equity_usdt=starting,
                realized_pnl_usdc=realized,
                market_marks=market_marks,
                current_ms=current_ms,
            )
            if marked["marks_used"] > 0:
                equity = float(marked["current_equity_usdt"])
                net_pnl = float(marked["estimated_net_pnl_usdc"])
                _append_fast_equity_point(settings, state, marked, current_ms)
            else:
                equity = round(starting + realized, 6)
                net_pnl = round(equity - starting, 6)
                marked["current_equity_usdt"] = equity
                marked["estimated_net_pnl_usdc"] = net_pnl
                marked["realized_pnl_usdc"] = round(realized, 6)
            if settings is not None:
                try:
                    persist_simulation_state(settings, state)
                except OSError:
                    _noter_echec("hl_observer/ui/status_routes.py:190")
        else:
            if (sltp_report["closed_count"] or quality_exit_report["closed_count"]) and settings is not None:
                try:
                    persist_simulation_state(settings, state)
                except OSError:
                    _noter_echec("hl_observer/ui/status_routes.py:196")
        external_bridge = build_external_github_bridge_payload()
        paper_ledger = _paper_ledger_projection_from_status_state(
            state=state,
            starting_equity_usdt=starting,
            marked=marked,
            current_ms=current_ms,
        )
        ledger_events = getattr(state, "simulation_ledger_events", None)
        if not isinstance(ledger_events, list):
            ledger_events = []
        position_integrity = _position_integrity_payload(
            raw_positions=raw_positions,
            marked=marked,
            ledger_events=ledger_events,
            current_ms=current_ms,
        )
        closed_trade_stats = paper_ledger.get("closed_trade_stats") if isinstance(paper_ledger, dict) else {}
        if not isinstance(closed_trade_stats, dict):
            closed_trade_stats = {}
        closed_trades = int(closed_trade_stats.get("closed_trades") or 0)
        winning_trades = int(closed_trade_stats.get("winning_trades") or 0)
        losing_trades = int(closed_trade_stats.get("losing_trades") or 0)
        winrate_pct = float(closed_trade_stats.get("winrate_pct") or 0.0)
        payload = {
            "running": True,
            "server_running": True,
            "engine_running": scanner["engine_running"],
            "read_only": True,
            # Local paper simulation, fed by REAL Hyperliquid market data.
            "mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA",
            "current_time_ms": current_ms,
            "engine_status": engine_status,
            "scanner": scanner,
            "equity_usdt": equity,
            "net_pnl_usdt": net_pnl,
            "realized_pnl_usdt": round(realized, 6),
            "unrealized_pnl_usdt": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
            "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
            "open_positions": len(marked["positions"]),
            "total_trades": closed_trades,
            "closed_trades": closed_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "flat_trades": int(closed_trade_stats.get("flat_trades") or 0),
            "winrate_pct": round(winrate_pct, 2),
            "winrate": f"{winrate_pct:.0f}%" if closed_trades else "0%",
            "positions": marked["positions"],
            "mark_to_market": marked["mark_to_market"],
            "mark_diagnostics": marked["mark_diagnostics"],
            "position_integrity": position_integrity,
            "paper_ledger": paper_ledger,
            "v12": build_v12_status_payload(engine_status=engine_status, scanner=scanner),
            "fusion_runtime": fusion_status,
            "fusion_persistent_adapter": fusion_apply_report,
            "sltp_runtime": sltp_report,
            "quality_guard_runtime": quality_exit_report,
            "external_github_bridge": external_bridge,
            "equity": {
                "current_equity_usdt": equity,
                "current_pnl_usdc": net_pnl,
                "realized_pnl_usdc": round(realized, 6),
                "unrealized_pnl_usdc": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
                "market_marks_available": int(marked.get("marks_used") or 0),
                "market_marks_missing": int(marked.get("marks_missing") or 0),
            },
            "bot_simulation": {
                "open_positions": marked["positions"],
                "current_equity_usdt": equity,
                "estimated_net_pnl_usdc": net_pnl,
                "realized_net_pnl_usdc": round(realized, 6),
                "unrealized_pnl_usdc": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
                "total_trades": closed_trades,
                "closed_trades": closed_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "flat_trades": int(closed_trade_stats.get("flat_trades") or 0),
                "winrate_pct": round(winrate_pct, 2),
                "closed_trade_stats": closed_trade_stats,
                "paper_ledger": paper_ledger,
                "position_integrity": position_integrity,
            },
            "counts": {},
            "message": "Paper local, donnees Hyperliquid reelles. No order, no key, no signature.",
        }
        diagnostic_logs = _maybe_export_status_diagnostics(
            settings=settings,
            payload=payload,
            ledger_events=ledger_events,
            current_ms=current_ms,
            cache=status_export_cache,
        )
        if diagnostic_logs is not None:
            payload["diagnostic_logs"] = diagnostic_logs
        return payload

    @router.get("/api/simulation/fusion-status")
    def simulation_fusion_status() -> dict[str, Any]:
        current_ms = now_ms()
        engine_status = _read_engine_status(settings)
        scanner = _scanner_payload_from_engine_status(engine_status, current_ms)
        return build_fusion_status_payload(
            state=state,
            engine_status=engine_status,
            scanner=scanner,
            settings=settings,
            current_ms=current_ms,
        ) | {"external_github_bridge": build_external_github_bridge_payload()}

    return router


def _maybe_export_status_diagnostics(
    *,
    settings: Settings | None,
    payload: dict[str, Any],
    ledger_events: list[Any],
    current_ms: int,
    cache: dict[str, Any],
) -> dict[str, str] | None:
    """Write compact live diagnostics for the fast status endpoint.

    The dashboard polls ``/api/simulation/status`` far more often than the
    heavier overview route. Exporting here keeps ``logs/logs a envoyer`` aligned
    with what the user is actually seeing, while the throttle avoids turning the
    UI refresh loop into a disk writer.
    """

    if settings is None:
        return None
    if _env_disabled("HYPERSMART_STATUS_EXPORT_DIAGNOSTICS"):
        return cache.get("last_result") if isinstance(cache.get("last_result"), dict) else None

    ledger_count = len(ledger_events) if isinstance(ledger_events, list) else 0
    last_export_ms = int(_safe_float(cache.get("last_export_ms")) or 0)
    last_ledger_count = int(_safe_float(cache.get("last_ledger_count")) or -1)
    min_interval_ms = max(500, FAST_STATUS_EXPORT_MIN_MS)
    if current_ms - last_export_ms < min_interval_ms and ledger_count == last_ledger_count:
        return cache.get("last_result") if isinstance(cache.get("last_result"), dict) else None

    export_payload = dict(payload)
    bot = dict(export_payload.get("bot_simulation") or {})
    compact_events = [row for row in ledger_events if isinstance(row, dict)][-2_000:]
    bot["ledger_events"] = compact_events
    bot["events"] = compact_events
    bot["paper_ledger"] = export_payload.get("paper_ledger")
    export_payload["bot_simulation"] = bot
    export_payload["paper_ledger"] = export_payload.get("paper_ledger")
    try:
        result = export_simulation_diagnostics(settings, export_payload)
    except OSError as exc:
        result = {
            "directory_status": "WRITE_FAILED",
            "write_warnings": f"{exc.__class__.__name__}: {exc}",
            "note": "Status diagnostics export failed; UI state remains read-only.",
        }
    cache["last_export_ms"] = current_ms
    cache["last_ledger_count"] = ledger_count
    cache["last_result"] = result
    return result


def _engine_status_path(settings: Settings | None) -> Path:
    if settings is not None:
        try:
            return simulation_state_path(settings).parent / ENGINE_STATUS_FILENAME
        except Exception:  # noqa: BLE001 - status endpoint must never fail on path resolution.
            _noter_echec("hl_observer/ui/status_routes.py:365")
    return Path("runtime") / "data" / ENGINE_STATUS_FILENAME


def _read_engine_status(settings: Settings | None) -> dict[str, Any]:
    path = _engine_status_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {
            "available": False,
            "path": str(path),
            "phase": "not_started",
            "message": "Aucun heartbeat moteur detecte. Garde la fenetre du lanceur ouverte.",
        }
    if not isinstance(payload, dict):
        return {"available": False, "path": str(path), "phase": "invalid", "message": "Heartbeat moteur invalide."}
    payload = dict(payload)
    payload["available"] = True
    payload.setdefault("path", str(path))
    return payload


def _empty_market_marks(reason: str, *, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prices": {},
        "sources": {},
        "latest_exchange_ts": None,
        "read_status": reason,
        "error": error,
    }
    return payload


def _apply_fast_status_sltp(state: UiState, market_marks: dict[str, Any], *, current_ms: int) -> dict[str, Any]:
    """Apply paper-only SL/TP to the fast status state, then book realized PnL.

    The legacy overview path already applied SL/TP. The fast live endpoint used
    by ``simulation_v2.html`` did not, so paper positions could remain open even
    after their protective local stop/take-profit should have closed them. This
    function keeps the accounting in the same local ledger used by the graph.
    """

    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    ledger = getattr(state, "simulation_ledger_events", None)
    prices = market_marks.get("prices") if isinstance(market_marks.get("prices"), dict) else {}
    if not isinstance(positions, dict) or not isinstance(ledger, list) or not prices:
        return {"enabled": False, "closed_count": 0, "reason": "NO_POSITIONS_OR_MARKS"}
    try:
        from hl_observer.paper_trading.sltp_runtime import sltp_config_from_env
        # V26 L2 : wrapper barrieres ajustees a la volatilite (flag OFF = passthrough exact)
        from hl_observer.paper_trading.vol_adjusted_barriers import apply_sltp_exits_vol_adjusted as apply_sltp_exits

        config = sltp_config_from_env()
        if config is None:
            return {"enabled": False, "closed_count": 0, "reason": "SLTP_DISABLED"}
        before_len = len(ledger)
        closed = apply_sltp_exits(
            positions,
            ledger,
            {str(coin).upper(): float(price) for coin, price in prices.items()},
            cost_bps=FAST_STATUS_EXIT_COST_BPS,
            now_ms=current_ms,
            config=config,
        )
    except Exception as exc:  # pragma: no cover - defensive live-status guard
        return {"enabled": True, "closed_count": 0, "reason": "SLTP_FAST_STATUS_FAILED", "error": str(exc)}

    new_events = [row for row in ledger[before_len:] if isinstance(row, dict)]
    realized_added = sum(float(row.get("estimated_net_pnl_usdc") or 0.0) for row in new_events)
    exit_costs_added = sum(float(row.get("fee_cost_usdc") or 0.0) for row in new_events)
    actual_closed = [
        row for row in closed
        if isinstance(row, dict) and not row.get("duplicate_close_ignored")
    ]
    duplicate_close_ignored = len(closed) - len(actual_closed)
    if closed:
        _release_processed_keys_for_closed_positions(state, closed)
    if new_events:
        state.simulation_realized_pnl_usdc += realized_added
        state.simulation_exit_costs_paid_usdc += exit_costs_added
        state.simulation_reproduced_exits_total += len(new_events)
    return {
        "enabled": True,
        "closed_count": len(actual_closed),
        "duplicate_close_ignored": duplicate_close_ignored,
        "ledger_events_added": len(new_events),
        "realized_pnl_added_usdc": round(realized_added, 6),
        "exit_costs_added_usdc": round(exit_costs_added, 6),
        "reason": "SLTP_FAST_STATUS_OK" if actual_closed else "SLTP_HOLD",
        "closed": closed,
    }


def _apply_fast_status_quality_exits(state: UiState, market_marks: dict[str, Any], *, current_ms: int) -> dict[str, Any]:
    """Close legacy copy positions that cannot prove their entry quality.

    This is not a profit switch. It realizes the current local paper PnL at the
    real mark already used by the metagraph, then writes a CLOSE ledger event so
    every graph move is explainable. It targets old copy-profile positions
    opened before the evidence fields became mandatory.
    """

    if _env_disabled("HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_ENABLED"):
        return {"enabled": False, "closed_count": 0, "reason": "QUALITY_GUARD_DISABLED"}
    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    ledger = getattr(state, "simulation_ledger_events", None)
    prices = market_marks.get("prices") if isinstance(market_marks.get("prices"), dict) else {}
    if not isinstance(positions, dict) or not isinstance(ledger, list) or not positions:
        return {"enabled": True, "closed_count": 0, "reason": "NO_POSITIONS"}
    if not prices:
        return {"enabled": True, "closed_count": 0, "reason": "NO_REAL_MARKS_FOR_QUALITY_EXIT"}

    min_age_ms = _env_int("HYPERSMART_LEGACY_POSITION_MIN_AGE_MS", 60_000)
    realize_negative = _env_truthy("HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_REALIZE_NEGATIVE")
    min_net_pnl_usdc = _env_float("HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_MIN_NET_PNL_USDC", 0.0)
    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    realized_added = 0.0
    exit_costs_added = 0.0
    for position_key, position in list(positions.items()):
        if not isinstance(position, dict):
            skipped.append({"position_key": str(position_key), "reason": "INVALID_POSITION_ROW"})
            continue
        quality_reason = _copy_position_quality_exit_reason(position, current_ms=current_ms, min_age_ms=min_age_ms)
        if not quality_reason:
            continue
        coin = str(position.get("coin") or position.get("market") or position.get("market_id") or "").upper()
        mark_price = _safe_float(prices.get(coin))
        if mark_price is None or mark_price <= 0:
            skipped.append({"position_key": str(position_key), "coin": coin, "reason": "NO_REAL_MARK_FOR_QUALITY_EXIT"})
            continue
        entry_price = (
            _safe_float(position.get("entry_price"))
            or _safe_float(position.get("avg_price"))
            or _safe_float(position.get("avg_entry_price"))
            or 0.0
        )
        size = _safe_float(position.get("size")) or 0.0
        if entry_price <= 0 or size == 0:
            skipped.append({"position_key": str(position_key), "coin": coin, "reason": "INVALID_POSITION_NUMBERS"})
            continue
        instance_id = _status_paper_position_instance_id(
            position_key=str(position_key),
            position=position,
            entry_price=entry_price,
            size=size,
        )
        if _status_full_close_already_exists(
            ledger,
            matched_position_key=str(position_key),
            instance_id=instance_id,
            entry_price=entry_price,
            size=size,
        ):
            _release_processed_key_for_position(state, position)
            positions.pop(position_key, None)
            skipped.append(
                {
                    "position_key": str(position_key),
                    "coin": coin,
                    "reason": "DUPLICATE_QUALITY_CLOSE_ALREADY_RECORDED",
                    "paper_position_instance_id": instance_id,
                }
            )
            continue
        if position_key not in positions:
            skipped.append(
                {
                    "position_key": str(position_key),
                    "coin": coin,
                    "reason": "QUALITY_CLOSE_POSITION_ALREADY_REMOVED_BEFORE_LEDGER",
                    "paper_position_instance_id": instance_id,
                }
            )
            continue
        closed_notional = abs(size * mark_price)
        gross_pnl = (mark_price - entry_price) * size
        exit_cost = closed_notional * FAST_STATUS_EXIT_COST_BPS / 10_000.0
        net_pnl = gross_pnl - exit_cost
        if net_pnl < min_net_pnl_usdc and not realize_negative:
            skipped.append(
                {
                    "position_key": str(position_key),
                    "coin": coin,
                    "reason": "QUALITY_GUARD_HOLD_TO_AVOID_FEE_DRAG",
                    "quality_reason": quality_reason,
                    "gross_pnl_usdc": round(gross_pnl, 8),
                    "fee_cost_usdc": round(exit_cost, 8),
                    "estimated_net_pnl_usdc": round(net_pnl, 8),
                    "min_net_pnl_usdc": round(min_net_pnl_usdc, 8),
                }
            )
            continue
        direction = str(position.get("direction") or position.get("side") or ("SHORT" if size < 0 else "LONG")).upper()
        event = {
            "delta_key": f"quality-guard-close:{position_key}:{current_ms}",
            "wallet_address": str(position.get("wallet_address") or position.get("leader_wallet") or ""),
            "coin": coin,
            "leader_action": "QUALITY_GUARD_LEGACY_POSITION_CLOSE",
            "leader_side": direction,
            "leader_price": mark_price,
            "leader_notional_usdc": closed_notional,
            "observed_at_ms": current_ms,
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "paper_action_type": "CLOSE",
            "paper_position_instance_id": instance_id,
            "source_delta_key": position.get("source_delta_key"),
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": round(net_pnl, 8),
            "gross_pnl_usdc": round(gross_pnl, 8),
            "fee_cost_usdc": round(exit_cost, 8),
            "copied_notional_usdt": closed_notional,
            "bot_position_size_after": 0.0,
            "matched_position_key": str(position_key),
            "entry_price": entry_price,
            "exit_price": mark_price,
            "average_entry_price": entry_price,
            "exit_method": "QUALITY_GUARD_LEGACY_UNEVIDENCED",
            "reason": quality_reason,
            "evidence_hash": str(position.get("last_evidence_hash") or position.get("source_delta_key") or position_key),
            "edge_remaining_bps": position.get("edge_remaining_bps"),
            "signal_age_ms": position.get("signal_age_ms"),
            "leader_wallets_count": position.get("leader_wallets_count"),
            "liquidity_score": position.get("liquidity_score"),
            "copy_degradation_bps": position.get("copy_degradation_bps"),
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
            "research_only": True,
            "simulation_only": True,
            "read_only": True,
            "external_action": False,
            "real_execution": False,
            "execution": "forbidden",
            "venue_endpoint": None,
            "secret_material_used": False,
        }
        ledger.append(event)
        _release_processed_key_for_position(state, position)
        removed_position = positions.pop(position_key, None)
        if removed_position is None:
            skipped.append(
                {
                    "position_key": str(position_key),
                    "coin": coin,
                    "reason": "QUALITY_CLOSE_POSITION_ALREADY_REMOVED",
                    "paper_position_instance_id": instance_id,
                }
            )
            continue
        realized_added += net_pnl
        exit_costs_added += exit_cost
        closed.append(
            {
                "position_key": str(position_key),
                "coin": coin,
                "direction": direction,
                "entry_price": round(entry_price, 8),
                "exit_price": round(mark_price, 8),
                "estimated_net_pnl_usdc": round(net_pnl, 8),
                "reason": quality_reason,
            }
        )
    if closed:
        state.simulation_realized_pnl_usdc += realized_added
        state.simulation_exit_costs_paid_usdc += exit_costs_added
        state.simulation_reproduced_exits_total += len(closed)
    return {
        "enabled": True,
        "closed_count": len(closed),
        "skipped_count": len(skipped),
        "realized_pnl_added_usdc": round(realized_added, 6),
        "exit_costs_added_usdc": round(exit_costs_added, 6),
        "reason": "QUALITY_GUARD_CLOSED_UNEVIDENCED_COPY_POSITIONS" if closed else "QUALITY_GUARD_HOLD",
        "closed": closed,
        "skipped": skipped[:20],
        "read_only": True,
        "real_execution": False,
    }


def _live_all_mids_marks(
    settings: Settings | None,
    *,
    raw_positions: list[dict[str, Any]],
    current_ms: int,
    cache: dict[str, Any],
    lock: threading.Lock,
) -> dict[str, Any]:
    """Optional fast read-only mark source for the metagraph.

    The UI status endpoint normally reads locally stored market snapshots. The
    launcher can opt into this short-cache `/info allMids` reader so an open
    paper position is marked close to real time without waiting for the heavier
    poll loop to finish a full scan. It never writes, never calls `/exchange`,
    and does nothing when no paper position is open.
    """

    if settings is None or not raw_positions or not _env_truthy("HYPERSMART_STATUS_LIVE_MARKS_ENABLED"):
        return _empty_market_marks("LIVE_MARKS_DISABLED")
    requested = {
        coin
        for row in raw_positions
        if isinstance(row, dict)
        for coin in [_infer_status_coin(row, index=0)]
        if coin
    }
    requested.discard("")
    if not requested:
        return _empty_market_marks("NO_OPEN_POSITION_COIN")

    with lock:
        fetched_at_ms = _safe_int(cache.get("fetched_at_ms")) or 0
        cached_prices = cache.get("prices") if isinstance(cache.get("prices"), dict) else {}
        if cached_prices and current_ms - fetched_at_ms <= LIVE_MARKS_MIN_INTERVAL_MS:
            return _marks_from_live_prices(cached_prices, requested, fetched_at_ms, read_status="OK_CACHE_LIVE_ALLMIDS")

        try:
            with httpx.Client(timeout=LIVE_MARKS_TIMEOUT_SECONDS) as client:
                response = client.post(settings.hyperliquid.info_base_url, json={"type": "allMids"})
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("allMids returned a non-object payload")
            prices = {
                str(coin).upper(): price
                for coin, raw_price in payload.items()
                if (price := _safe_float(raw_price)) is not None and price > 0
            }
            cache.update({"fetched_at_ms": current_ms, "prices": prices, "error": None})
            return _marks_from_live_prices(prices, requested, current_ms, read_status="OK_LIVE_ALLMIDS")
        except (httpx.HTTPError, ValueError, OSError) as exc:
            cache["error"] = f"{exc.__class__.__name__}: {exc}"
            if cached_prices and current_ms - fetched_at_ms <= LIVE_MARKS_MAX_STALE_MS:
                marks = _marks_from_live_prices(
                    cached_prices,
                    requested,
                    fetched_at_ms,
                    read_status="OK_STALE_CACHE_LIVE_ALLMIDS",
                )
                marks["error"] = cache["error"]
                return marks
            return _empty_market_marks("LIVE_ALLMIDS_READ_FAILED", error=cache["error"])


def _marks_from_live_prices(
    prices: dict[str, float],
    requested_coins: set[str],
    fetched_at_ms: int,
    *,
    read_status: str,
) -> dict[str, Any]:
    selected = {
        coin: float(price)
        for coin, price in prices.items()
        if coin in requested_coins and float(price) > 0
    }
    return {
        "prices": selected,
        "sources": {coin: "liveAllMidsStatus" for coin in selected},
        "latest_exchange_ts": int(fetched_at_ms),
        "read_status": read_status if selected else "LIVE_ALLMIDS_NO_MATCHING_MARK",
        "error": None,
        "read_only": True,
        "endpoint": "/info",
        "request_type": "allMids",
    }


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _env_disabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "")))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return float(default)


def _latest_mid_prices_from_snapshot(raw_snapshot: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(raw_snapshot, dict):
        return {}
    snapshot = raw_snapshot.get("prices") if isinstance(raw_snapshot.get("prices"), dict) else raw_snapshot
    prices: dict[str, float] = {}
    for coin, value in snapshot.items():
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            prices[str(coin).upper()] = price
    return prices


def _latest_market_marks_from_snapshots(snapshots: list[MarketSnapshot]) -> dict[str, Any]:
    prices: dict[str, float] = {}
    sources: dict[str, str] = {}
    latest_exchange_ts: int | None = None
    for snapshot in sorted(snapshots, key=lambda row: (row.exchange_ts or 0, row.id or 0), reverse=True):
        if snapshot.exchange_ts is not None and latest_exchange_ts is None:
            latest_exchange_ts = int(snapshot.exchange_ts)
        for coin, price in _latest_mid_prices_from_snapshot(snapshot.raw_json).items():
            if coin in prices:
                continue
            prices[coin] = price
            sources[coin] = snapshot.source or "market_snapshot"
    return {
        "prices": prices,
        "sources": sources,
        "latest_exchange_ts": latest_exchange_ts,
        "read_status": "OK" if prices else "NO_USABLE_MARK",
        "error": None,
    }


def _mark_to_market_positions(
    raw_positions: list[dict[str, Any]],
    *,
    starting_equity_usdt: float,
    realized_pnl_usdc: float,
    market_marks: dict[str, Any],
    current_ms: int,
) -> dict[str, Any]:
    prices = market_marks.get("prices") if isinstance(market_marks.get("prices"), dict) else {}
    sources = market_marks.get("sources") if isinstance(market_marks.get("sources"), dict) else {}
    positions: list[dict[str, Any]] = []
    unrealized_pnl = 0.0
    open_exposure = 0.0
    marks_used = 0
    marks_missing = 0
    invalid_positions: list[dict[str, Any]] = []
    for index, raw_position in enumerate(raw_positions):
        normalized = _normalize_position_for_status(raw_position, index=index)
        coin = normalized["coin"]
        direction = normalized["direction"]
        size = abs(float(normalized["size"]))
        entry_price = float(normalized["entry_price"])
        if not _is_valid_status_position(normalized):
            invalid_positions.append(
                {
                    "position_id": normalized.get("position_id"),
                    "coin": coin,
                    "direction": direction,
                    "size": size,
                    "entry_price": entry_price,
                    "reason": "INVALID_POSITION_FIELDS_SKIPPED",
                }
            )
            continue
        mark_price = prices.get(coin)
        mark_source = sources.get(coin)
        market_mark_available = mark_price is not None and mark_price > 0
        if market_mark_available:
            marks_used += 1
            position_notional = size * float(mark_price)
            open_exposure += position_notional
            if direction == "SHORT":
                gross_unrealized = (entry_price - float(mark_price)) * size
            else:
                gross_unrealized = (float(mark_price) - entry_price) * size
            exit_cost_estimate = position_notional * FAST_STATUS_EXIT_COST_BPS / 10_000.0
            net_unrealized = gross_unrealized - exit_cost_estimate
            unrealized_pnl += net_unrealized
        else:
            marks_missing += 1
            mark_price = None
            mark_source = "MARK_MISSING_NO_FAST_MTM"
            position_notional = size * entry_price
            gross_unrealized = 0.0
            exit_cost_estimate = 0.0
            net_unrealized = 0.0
        enriched = dict(normalized)
        enriched.update(
            {
                "mark_price": round(float(mark_price), 8) if mark_price is not None else None,
                "mark_source": mark_source,
                "mark_age_ms": _mark_age_ms(market_marks, current_ms) if market_mark_available else None,
                "market_mark_available": bool(market_mark_available),
                "notional_usdt": round(position_notional, 6),
                "gross_unrealized_pnl_usdc": round(gross_unrealized, 6),
                "exit_cost_estimate_usdc": round(exit_cost_estimate, 6),
                "unrealized_pnl_usdc": round(net_unrealized, 6),
                "last_mark_at_ms": int(market_marks.get("latest_exchange_ts") or current_ms) if market_mark_available else None,
                "mark_formula": "short: (entry-mark)*size-cost" if direction == "SHORT" else "long: (mark-entry)*size-cost",
                "research_only": True,
            }
        )
        positions.append(enriched)
    net_pnl = realized_pnl_usdc + unrealized_pnl
    return {
        "positions": positions,
        "realized_pnl_usdc": round(realized_pnl_usdc, 6),
        "unrealized_pnl_usdc": round(unrealized_pnl, 6),
        "estimated_net_pnl_usdc": round(net_pnl, 6),
        "current_equity_usdt": round(starting_equity_usdt + net_pnl, 6),
        "open_exposure_usdt": round(open_exposure, 6),
        "marks_used": marks_used,
        "marks_missing": marks_missing,
        "mark_diagnostics": _build_mark_diagnostics(
            positions=positions,
            market_marks=market_marks,
            current_ms=current_ms,
            marks_used=marks_used,
            marks_missing=marks_missing,
            invalid_positions=invalid_positions,
        ),
        "mark_to_market": {
            "source": "LIVE_HYPERLIQUID_ALLMIDS_OR_LOCAL_SNAPSHOTS",
            "read_status": market_marks.get("read_status"),
            "error": market_marks.get("error"),
            "live_read_status": market_marks.get("live_read_status"),
            "live_error": market_marks.get("live_error"),
            "endpoint": market_marks.get("endpoint"),
            "request_type": market_marks.get("request_type"),
            "latest_market_snapshot_ms": market_marks.get("latest_exchange_ts"),
            "marks_used": marks_used,
            "marks_missing": marks_missing,
            "invalid_positions_skipped": len(invalid_positions),
            "cost_model_bps": FAST_STATUS_EXIT_COST_BPS,
            "no_fallback_position_created": True,
            "official_simulation": "simulation_v2.html",
            "heartbeat_is_diagnostic_only": True,
        },
    }


def _paper_ledger_projection_from_status_state(
    *,
    state: UiState,
    starting_equity_usdt: float,
    marked: dict[str, Any],
    current_ms: int,
) -> dict[str, Any]:
    """Expose a strict ledger-like accounting view for the live simulation UI.

    The heavy simulation loop still owns ``state.simulation_ledger_events``.
    This endpoint does not invent trades; it only reconciles the existing
    realized PnL, current mark-to-market and equity history into one audited
    snapshot so PnL jumps can be traced from logs.
    """

    realized = _safe_float(marked.get("realized_pnl_usdc")) or 0.0
    unrealized = _safe_float(marked.get("unrealized_pnl_usdc")) or 0.0
    equity = _safe_float(marked.get("current_equity_usdt"))
    if equity is None:
        equity = float(starting_equity_usdt) + realized + unrealized
    ledger_events = getattr(state, "simulation_ledger_events", None)
    if not isinstance(ledger_events, list):
        ledger_events = []
    history = getattr(state, "simulation_equity_history", None)
    if not isinstance(history, list):
        history = []
    # Existing UI replay events already embed entry/exit costs in realized and
    # mark-to-market values. Reporting legacy costs separately avoids subtracting
    # them twice in the reconciliation formula.
    entry_costs = _safe_float(getattr(state, "simulation_entry_costs_paid_usdc", 0.0)) or 0.0
    exit_costs = _safe_float(getattr(state, "simulation_exit_costs_paid_usdc", 0.0)) or 0.0
    reconciliation = reconcile_pnl(
        starting_balance_usdc=float(starting_equity_usdt),
        realized_pnl_usdc=realized,
        unrealized_pnl_usdc=unrealized,
        fees_paid_usdc=0.0,
        funding_net_usdc=0.0,
        actual_equity_usdc=float(equity),
        tolerance_usdc=0.02,
    )
    event_counts: dict[str, int] = {}
    for row in ledger_events:
        if not isinstance(row, dict):
            continue
        key = str(row.get("paper_action_type") or row.get("bot_replay_action") or row.get("status") or "UNKNOWN")
        event_counts[key] = event_counts.get(key, 0) + 1
    spike_links = _ledger_spike_links_from_status_state(
        history=history,
        ledger_events=ledger_events,
    )
    closed_trade_stats = _ledger_closed_trade_stats(ledger_events)
    return {
        "source": "UI_STATE_LEDGER_PROJECTION",
        "read_only": True,
        "external_action": False,
        "current_time_ms": int(current_ms),
        "starting_balance_usdc": round(float(starting_equity_usdt), 6),
        "realized_pnl_usdc": round(realized, 6),
        "unrealized_pnl_usdc": round(unrealized, 6),
        "equity_usdc": round(float(equity), 6),
        "open_positions_count": len(marked.get("positions") or []),
        "event_count": len(ledger_events),
        "event_counts": event_counts,
        "closed_trade_stats": closed_trade_stats,
        "winning_trades": closed_trade_stats["winning_trades"],
        "losing_trades": closed_trade_stats["losing_trades"],
        "flat_trades": closed_trade_stats["flat_trades"],
        "closed_trades": closed_trade_stats["closed_trades"],
        "winrate_pct": closed_trade_stats["winrate_pct"],
        "legacy_costs_reported_usdc": round(entry_costs + exit_costs, 6),
        "cost_accounting": "legacy UI costs are already embedded in realized/mark values; not subtracted again here",
        "reconciliation": asdict(reconciliation),
        # PISTE 12 -- DEUX MOTEURS, DEUX PnL. Un chiffre unique melange deux maladies
        # (le Grinder meurt des frais, le Sniper de la fraicheur) et laisse un moteur qui gagne
        # masquer un moteur qui saigne. `moteurs_inactifs` dit tout haut qu'un moteur ne trade
        # pas -- c'est ainsi que le Grinder est reste eteint sans que personne le voie.
        "pnl_par_moteur": _rapport_par_moteur(ledger_events),
        "spike_diagnostics": _equity_spike_diagnostics(history),
        "spike_links": spike_links,
        "formula": "equity = starting_balance + realized_pnl + unrealized_pnl",
        "no_fake_pnl": True,
    }


def _position_integrity_payload(
    *,
    raw_positions: list[dict[str, Any]],
    marked: dict[str, Any],
    ledger_events: list[dict[str, Any]],
    current_ms: int,
) -> dict[str, Any]:
    """Explain why a visible paper position may disappear or be skipped.

    Users were seeing positions vanish from the dashboard while the win/loss
    counters stayed unchanged. That is expected only for invalid/orphan local
    state cleanup; it must be visible in the API instead of looking like a
    phantom close. This payload is diagnostic-only and never creates PnL.
    """

    mark_diagnostics = marked.get("mark_diagnostics") if isinstance(marked.get("mark_diagnostics"), dict) else {}
    invalid_positions = mark_diagnostics.get("invalid_positions")
    if not isinstance(invalid_positions, list):
        invalid_positions = []
    valid_positions = marked.get("positions") if isinstance(marked.get("positions"), list) else []

    cleanup_events: list[dict[str, Any]] = []
    stale_cleanup_events = 0
    for row in ledger_events[-300:]:
        if not isinstance(row, dict):
            continue
        action = str(row.get("bot_replay_action") or row.get("paper_action_type") or row.get("status") or "").upper()
        reason = str(row.get("reason") or row.get("refusal_reason") or "").upper()
        if action != "STATE_CLEANUP" and reason != "ORPHAN_VIRTUAL_POSITION_DROPPED_NO_ENTRY_LEDGER":
            continue
        observed_at = _safe_int(row.get("observed_at_ms") or row.get("event_time_ms") or row.get("time_ms"))
        age_ms = None if observed_at is None else max(0, int(current_ms) - int(observed_at))
        if age_ms is not None and age_ms > 15 * 60 * 1000:
            stale_cleanup_events += 1
            continue
        cleanup_events.append(
            {
                "observed_at_ms": observed_at,
                "age_ms": age_ms,
                "coin": row.get("coin"),
                "side": row.get("leader_side") or row.get("side") or row.get("direction"),
                "matched_position_key": row.get("matched_position_key"),
                "delta_key": row.get("delta_key"),
                "reason": row.get("reason") or "ORPHAN_VIRTUAL_POSITION_DROPPED_NO_ENTRY_LEDGER",
                "pnl_impact_usdc": row.get("estimated_net_pnl_usdc"),
            }
        )

    raw_count = len(raw_positions)
    valid_count = len(valid_positions)
    invalid_count = len(invalid_positions)
    recent_cleanup_count = len(cleanup_events)
    if invalid_count or recent_cleanup_count:
        status = "WARN"
    else:
        status = "OK"
    if invalid_count:
        message = f"{invalid_count} position(s) locale(s) ignoree(s): champs incomplets ou coin inconnu."
    elif recent_cleanup_count:
        message = f"{recent_cleanup_count} nettoyage(s) recent(s) de position orpheline: aucun PnL cree."
    else:
        message = "Positions paper coherentes avec le ledger visible."

    return {
        "status": status,
        "message": message,
        "raw_positions_seen": raw_count,
        "valid_positions": valid_count,
        "invalid_positions_skipped": invalid_count,
        "invalid_positions": invalid_positions[:10],
        "orphan_cleanup_events_recent": recent_cleanup_count,
        "recent_orphan_cleanup_events": cleanup_events[-10:],
        "stale_orphan_cleanup_events_ignored": stale_cleanup_events,
        "dashboard_should_hide_invalid_positions": True,
        "pnl_impact": "NONE_FOR_INVALID_ORPHAN_CLEANUP",
        "read_only": True,
        "external_action": False,
    }


def _ledger_closed_trade_stats(ledger_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute visible win/loss counters from real paper close/reduce events.

    The graph already used the same ledger for PnL, but the fast endpoint did
    not expose closed-trade counters. That made local paper exits look like
    disappearing positions in the UI. This helper is deliberately strict:
    only explicit CLOSE/REDUCE paper events with numeric realized PnL count.
    """

    entry_context_by_key = _ledger_entry_context_index(ledger_events)
    closed: list[dict[str, Any]] = []
    seen_full_closes: set[str] = set()
    duplicate_full_closes_ignored = 0
    entry_context_found_count = 0
    for row in ledger_events:
        if not isinstance(row, dict):
            continue
        paper_action = str(row.get("paper_action_type") or "").upper()
        replay_action = str(row.get("bot_replay_action") or "").upper()
        combined = f"{paper_action} {replay_action}"
        if not any(token in combined for token in ("CLOSE", "REDUCE", "EXIT", "TRAILING_STOP", "STOP_LOSS", "TAKE_PROFIT")):
            continue
        pnl = _safe_float(row.get("estimated_net_pnl_usdc"))
        if pnl is None:
            continue
        identity = _closed_trade_identity(row)
        is_full_close = "CLOSE" in combined or "TAKE_PROFIT" in combined or "STOP_LOSS" in combined
        if is_full_close and identity:
            if identity in seen_full_closes:
                duplicate_full_closes_ignored += 1
                continue
            seen_full_closes.add(identity)
        entry_context = _lookup_ledger_entry_context(row, identity, entry_context_by_key)
        if entry_context:
            entry_context_found_count += 1
        enriched = {
            "delta_key": row.get("delta_key"),
            "paper_position_instance_id": row.get("paper_position_instance_id"),
            "source_delta_key": row.get("source_delta_key"),
            "observed_at_ms": row.get("observed_at_ms"),
            "coin": row.get("coin"),
            "side": row.get("leader_side") or row.get("side") or row.get("direction"),
            "paper_action_type": paper_action or replay_action or "CLOSE",
            "bot_replay_action": row.get("bot_replay_action"),
            "estimated_net_pnl_usdc": round(pnl, 8),
            "gross_pnl_usdc": row.get("gross_pnl_usdc"),
            "fee_cost_usdc": row.get("fee_cost_usdc"),
            "entry_price": row.get("entry_price") or row.get("average_entry_price"),
            "exit_price": row.get("exit_price"),
            "exit_method": row.get("exit_method"),
            "reason": row.get("reason"),
            "matched_position_key": row.get("matched_position_key"),
            "dedupe_identity": identity,
            "entry_context_found": bool(entry_context),
        }
        if entry_context:
            enriched.update(entry_context)
        closed.append(enriched)
    wins = sum(1 for row in closed if float(row["estimated_net_pnl_usdc"]) > 0)
    losses = sum(1 for row in closed if float(row["estimated_net_pnl_usdc"]) < 0)
    flats = len(closed) - wins - losses
    decisive = wins + losses
    winrate_pct = (wins / decisive * 100.0) if decisive else 0.0
    return {
        "closed_trades": len(closed),
        "winning_trades": wins,
        "losing_trades": losses,
        "flat_trades": flats,
        "winrate_pct": round(winrate_pct, 2),
        "total_closed_pnl_usdc": round(sum(float(row["estimated_net_pnl_usdc"]) for row in closed), 8),
        "duplicate_full_closes_ignored": duplicate_full_closes_ignored,
        "entry_context_found": entry_context_found_count,
        "entry_context_missing": max(0, len(closed) - entry_context_found_count),
        "recent_closed_trades": closed[-20:],
        "source": "simulation_ledger_events",
        "no_fake_pnl": True,
    }


def _ledger_entry_context_index(ledger_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index paper entry evidence so close rows can explain why they existed.

    The PnL truth remains the close event. This context only helps diagnostics,
    replay filters, and the UI answer: "why was this paper position opened?"
    """

    index: dict[str, dict[str, Any]] = {}
    for row in ledger_events:
        if not isinstance(row, dict):
            continue
        paper_action = str(row.get("paper_action_type") or "").upper()
        replay_action = str(row.get("bot_replay_action") or "").upper()
        combined = f"{paper_action} {replay_action}"
        if not any(token in combined for token in ("OPEN", "ENTRY", "INCREASE", "ADD")):
            continue
        if any(token in combined for token in ("CLOSE", "EXIT", "STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP")):
            continue
        context = _entry_context_from_row(row)
        for key in _entry_context_keys(row, _closed_trade_identity(row)):
            index[key] = context
    return index


def _lookup_ledger_entry_context(
    row: dict[str, Any],
    identity: str,
    index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    for key in _entry_context_keys(row, identity):
        context = index.get(key)
        if context:
            return context
    return {}


def _entry_context_keys(row: dict[str, Any], identity: str | None = None) -> tuple[str, ...]:
    keys: list[str] = []
    for prefix, raw in (
        ("instance", row.get("paper_position_instance_id")),
        ("source", row.get("source_delta_key")),
        ("delta", row.get("delta_key")),
        ("matched", row.get("matched_position_key")),
        ("identity", identity),
    ):
        value = str(raw or "").strip()
        if value:
            keys.append(f"{prefix}:{value}")
    coin = str(row.get("coin") or "").strip().upper()
    side = str(row.get("leader_side") or row.get("side") or row.get("direction") or "").strip().upper()
    entry_price = _safe_float(row.get("entry_price") or row.get("average_entry_price"))
    if coin and side and entry_price is not None:
        keys.append(f"coin-side-entry:{coin}:{side}:{entry_price:.12g}")
    return tuple(dict.fromkeys(keys))


def _entry_context_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_delta_key": row.get("delta_key"),
        "entry_observed_at_ms": row.get("observed_at_ms") or row.get("timestamp_ms") or row.get("recorded_at_ms"),
        "entry_edge_remaining_bps": row.get("edge_remaining_bps"),
        "entry_signal_age_ms": row.get("signal_age_ms"),
        "entry_copy_degradation_bps": row.get("copy_degradation_bps"),
        "entry_consensus_wallets": row.get("consensus_wallets") or row.get("wallet_count"),
        "entry_copied_notional_usdt": row.get("copied_notional_usdt") or row.get("notional_usdc") or row.get("leader_notional_usdc"),
        "entry_position_mode": row.get("position_mode"),
        "entry_reason": row.get("reason"),
        "entry_evidence_hash": row.get("evidence_hash") or row.get("last_evidence_hash"),
        "entry_expected_net_edge_usdt": row.get("expected_net_edge_usdt"),
        "entry_cost_guard_reasons": row.get("cost_guard_reasons"),
    }


def _closed_trade_identity(row: dict[str, Any]) -> str:
    instance_id = str(row.get("paper_position_instance_id") or "").strip()
    if instance_id:
        return instance_id
    action_blob = f"{row.get('paper_action_type') or ''} {row.get('bot_replay_action') or ''} {row.get('exit_method') or ''}".upper()
    is_full_close = "CLOSE" in action_blob or "TAKE_PROFIT" in action_blob or "STOP_LOSS" in action_blob
    delta_key = str(row.get("delta_key") or "").strip()
    if delta_key and not is_full_close:
        return f"delta:{delta_key}"
    matched_key = str(row.get("matched_position_key") or "").strip()
    if not matched_key:
        if delta_key:
            return f"delta:{delta_key}"
        return ""
    source = str(row.get("source_delta_key") or "").strip()
    if source:
        return f"{matched_key}|src:{source}"
    entry = _safe_float(row.get("entry_price") or row.get("average_entry_price"))
    size = _safe_float(row.get("size_closed") or row.get("size_before"))
    method = str(row.get("exit_method") or row.get("reason") or "").strip()
    entry_part = f"{entry:.12g}" if entry is not None else "unknown_entry"
    size_part = f"{abs(size):.12g}" if size is not None else "unknown_size"
    return f"{matched_key}|entry:{entry_part}|size:{size_part}|method:{method}"


def _status_paper_position_instance_id(
    *,
    position_key: str,
    position: dict[str, Any],
    entry_price: float,
    size: float,
) -> str:
    source = str(
        position.get("source_delta_key")
        or position.get("last_paper_ref")
        or position.get("last_evidence_hash")
        or ""
    ).strip()
    if source:
        return f"{position_key}|src:{source}"
    opened_at_ms = _safe_int(
        position.get("opened_at_ms")
        or position.get("created_at_ms")
        or position.get("observed_at_ms")
        or position.get("entry_observed_at_ms")
    )
    if opened_at_ms:
        return f"{position_key}|opened:{opened_at_ms}|entry:{entry_price:.12g}|size:{abs(size):.12g}"
    return f"{position_key}|entry:{entry_price:.12g}|size:{abs(size):.12g}"


def _status_full_close_already_exists(
    ledger: list[Any],
    *,
    matched_position_key: str,
    instance_id: str,
    entry_price: float,
    size: float,
) -> bool:
    fallback = f"{matched_position_key}|entry:{entry_price:.12g}|size:{abs(size):.12g}"
    for row in ledger:
        if not isinstance(row, dict):
            continue
        action_blob = f"{row.get('paper_action_type') or ''} {row.get('bot_replay_action') or ''} {row.get('exit_method') or ''}".upper()
        if "CLOSE" not in action_blob and "TAKE_PROFIT" not in action_blob and "STOP_LOSS" not in action_blob:
            continue
        if str(row.get("matched_position_key") or "") != matched_position_key:
            continue
        existing_instance = str(row.get("paper_position_instance_id") or "").strip()
        if existing_instance and existing_instance == instance_id:
            return True
        if not existing_instance:
            existing_entry = _safe_float(row.get("entry_price") or row.get("average_entry_price"))
            existing_size = _safe_float(row.get("size_closed") or row.get("size_before"))
            entry_part = f"{entry_price:.12g}" if existing_entry is None else f"{existing_entry:.12g}"
            size_part = f"{abs(size):.12g}" if existing_size is None else f"{abs(existing_size):.12g}"
            if f"{matched_position_key}|entry:{entry_part}|size:{size_part}" == fallback:
                return True
    return False


def _release_processed_keys_for_closed_positions(state: UiState, closed: list[dict[str, Any]]) -> None:
    """Free duplicate guards after a paper position has genuinely closed."""

    positions = getattr(state, "simulation_virtual_positions", {}) or {}
    if not isinstance(positions, dict):
        return
    for row in closed:
        if not isinstance(row, dict):
            continue
        source_delta_key = str(row.get("source_delta_key") or "")
        if source_delta_key:
            processed = getattr(state, "simulation_processed_delta_keys", None)
            if isinstance(processed, set):
                processed.discard(source_delta_key)
        key = str(row.get("position_key") or row.get("matched_position_key") or "")
        position = positions.get(key)
        if isinstance(position, dict):
            _release_processed_key_for_position(state, position)


def _release_processed_key_for_position(state: UiState, position: dict[str, Any]) -> None:
    processed = getattr(state, "simulation_processed_delta_keys", None)
    if not isinstance(processed, set):
        return
    source_delta_key = str(position.get("source_delta_key") or "")
    if source_delta_key:
        processed.discard(source_delta_key)
    last_paper_ref = str(position.get("last_paper_ref") or "")
    if last_paper_ref:
        processed.discard(f"fusion-runtime-order:{last_paper_ref}")


def _ledger_spike_links_from_status_state(
    *,
    history: list[dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    threshold_usdc: float = 0.75,
    window_ms: int = 2_000,
) -> dict[str, Any]:
    """Small status-route version of graph spike -> ledger event linking.

    It is intentionally pure and in-memory only, so the fast dashboard tick can
    explain normal PnL movements without waiting for the heavy overview route.
    """

    points = [
        row
        for row in sorted(history, key=lambda item: _safe_int(item.get("timestamp_ms")) or 0)
        if isinstance(row, dict) and _safe_float(row.get("current_equity_usdt")) is not None
    ]
    typed_events = [
        row
        for row in ledger_events
        if isinstance(row, dict) and _safe_int(row.get("observed_at_ms")) is not None
    ]
    spikes: list[dict[str, Any]] = []
    largest = 0.0
    for previous, current in zip(points, points[1:]):
        previous_equity = _safe_float(previous.get("current_equity_usdt"))
        current_equity = _safe_float(current.get("current_equity_usdt"))
        if previous_equity is None or current_equity is None:
            continue
        jump = current_equity - previous_equity
        largest = max(largest, abs(jump))
        if abs(jump) < threshold_usdc:
            continue
        current_ts = _safe_int(current.get("timestamp_ms")) or 0
        nearby_context_events = [
            {
                "delta_key": event.get("delta_key"),
                "observed_at_ms": event.get("observed_at_ms"),
                "coin": event.get("coin"),
                "wallet_address": event.get("wallet_address"),
                "bot_replay_action": event.get("bot_replay_action"),
                "paper_action_type": event.get("paper_action_type"),
                "status": event.get("status"),
                "estimated_net_pnl_usdc": event.get("estimated_net_pnl_usdc"),
                "fee_cost_usdc": event.get("fee_cost_usdc"),
                "reason": event.get("reason"),
                "evidence_hash": event.get("evidence_hash"),
            }
            for event in typed_events
            if abs((_safe_int(event.get("observed_at_ms")) or 0) - current_ts) <= window_ms
        ][:8]
        nearby_pnl_events = [
            event for event in nearby_context_events if _ledger_event_can_move_pnl(event)
        ]
        explained_by_market_mark = _graph_spike_is_mark_to_market(previous, current)
        spikes.append(
            {
                "timestamp_ms": current_ts,
                "jump_usdc": round(jump, 6),
                "from_equity_usdc": round(previous_equity, 6),
                "to_equity_usdc": round(current_equity, 6),
                "from_source": previous.get("source"),
                "to_source": current.get("source"),
                "nearby_ledger_events_count": len(nearby_pnl_events),
                "nearby_ledger_events": nearby_pnl_events,
                "nearby_context_events_count": len(nearby_context_events),
                "nearby_context_events": nearby_context_events,
                "explained_by_nearby_ledger_event": bool(nearby_pnl_events),
                "explained_by_mark_to_market": explained_by_market_mark,
                "explanation": (
                    "MARK_TO_MARKET_PRICE_MOVE_ON_OPEN_PAPER_POSITIONS"
                    if explained_by_market_mark
                    else ("LEDGER_EVENT_NEARBY" if nearby_pnl_events else "UNEXPLAINED")
                ),
                "explained": bool(nearby_pnl_events) or explained_by_market_mark,
            }
        )
    unexplained = [row for row in spikes if not row.get("explained")]
    return {
        "threshold_usdc": threshold_usdc,
        "window_ms": window_ms,
        "history_points": len(points),
        "ledger_events_checked": len(typed_events),
        "largest_abs_jump_usdc": round(largest, 6),
        "spike_count": len(spikes),
        "unexplained_spike_count": len(unexplained),
        "recent_spikes": spikes[-20:],
        "status": "OK" if not unexplained else "UNEXPLAINED_SPIKES_NEED_LEDGER_REVIEW",
        "read_only": True,
        "execution": "forbidden",
    }


def _graph_spike_is_mark_to_market(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_source = str(previous.get("source") or "")
    current_source = str(current.get("source") or "")
    if previous_source != "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID":
        return False
    if current_source != "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID":
        return False
    previous_open = _safe_int(previous.get("open_positions")) or 0
    current_open = _safe_int(current.get("open_positions")) or 0
    return max(previous_open, current_open) > 0


def _ledger_event_can_move_pnl(event: dict[str, Any]) -> bool:
    """Return True only for events that can genuinely affect paper PnL.

    NO_TRADE/refusal rows are useful context, but they must not "explain" a
    graph jump. A PnL spike should link to an entry/exit/reduce, explicit fees,
    or a paper mark/update event.
    """

    replay_action = str(event.get("bot_replay_action") or "").upper()
    paper_action = str(event.get("paper_action_type") or "").upper()
    status = str(event.get("status") or "").upper()
    reason = str(event.get("reason") or "").upper()
    refusal_tokens = ("NO_TRADE", "REJECT", "REFUSED", "IGNORED", "SKIP")
    if any(token in replay_action for token in refusal_tokens):
        return False
    if any(token in paper_action for token in refusal_tokens):
        return False
    if any(token in status for token in refusal_tokens):
        return False
    if reason and any(token in reason for token in refusal_tokens):
        return False
    for numeric_key in ("estimated_net_pnl_usdc", "fee_cost_usdc", "funding_cost_usdc"):
        value = _safe_float(event.get(numeric_key))
        if value is not None and abs(value) > 0.0:
            return True
    pnl_actions = (
        "OPEN",
        "ENTRY",
        "ADD",
        "INCREASE",
        "REDUCE",
        "CLOSE",
        "EXIT",
        "PARTIAL",
        "FEE",
        "FUNDING",
        "MARK",
        "PAPER",
    )
    combined = f"{paper_action} {replay_action}"
    return any(token in combined for token in pnl_actions)


def _equity_spike_diagnostics(history: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in history if isinstance(row, dict)]
    rows = sorted(rows, key=lambda row: _safe_int(row.get("timestamp_ms")) or 0)
    previous: dict[str, Any] | None = None
    spikes: list[dict[str, Any]] = []
    largest_abs_jump = 0.0
    for row in rows:
        current_equity = _safe_float(row.get("current_equity_usdt"))
        if current_equity is None:
            continue
        if previous is not None:
            previous_equity = _safe_float(previous.get("current_equity_usdt"))
            if previous_equity is not None:
                jump = current_equity - previous_equity
                largest_abs_jump = max(largest_abs_jump, abs(jump))
                if abs(jump) >= 0.75:
                    spikes.append(
                        {
                            "timestamp_ms": _safe_int(row.get("timestamp_ms")),
                            "jump_usdc": round(jump, 6),
                            "from_equity_usdc": round(previous_equity, 6),
                            "to_equity_usdc": round(current_equity, 6),
                            "from_source": previous.get("source"),
                            "to_source": row.get("source"),
                            "open_positions": row.get("open_positions"),
                        }
                    )
        previous = row
    return {
        "history_points": len(rows),
        "largest_abs_jump_usdc": round(largest_abs_jump, 6),
        "spike_threshold_usdc": 0.75,
        "spike_count": len(spikes),
        "recent_spikes": spikes[-20:],
        "interpretation": "OK_NO_LARGE_UNEXPLAINED_JUMP" if not spikes else "CHECK_LEDGER_EVENTS_AROUND_SPIKES",
    }


def _mark_age_ms(market_marks: dict[str, Any], current_ms: int) -> int | None:
    latest = _safe_int(market_marks.get("latest_exchange_ts"))
    if latest is None:
        return None
    return max(0, int(current_ms) - int(latest))


def _build_mark_diagnostics(
    *,
    positions: list[dict[str, Any]],
    market_marks: dict[str, Any],
    current_ms: int,
    marks_used: int,
    marks_missing: int,
    invalid_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    per_position: list[dict[str, Any]] = []
    for position in positions:
        available = bool(position.get("market_mark_available"))
        per_position.append(
            {
                "position_id": position.get("position_id"),
                "coin": position.get("coin"),
                "direction": position.get("direction"),
                "entry_price": position.get("entry_price"),
                "mark_price": position.get("mark_price"),
                "mark_source": position.get("mark_source"),
                "mark_age_ms": position.get("mark_age_ms"),
                "gross_unrealized_pnl_usdc": position.get("gross_unrealized_pnl_usdc"),
                "exit_cost_estimate_usdc": position.get("exit_cost_estimate_usdc"),
                "net_unrealized_pnl_usdc": position.get("unrealized_pnl_usdc"),
                "last_replay_action": position.get("last_replay_action"),
                "last_evidence_hash": position.get("last_evidence_hash"),
                "last_paper_ref": position.get("last_paper_ref"),
                "last_v9_decision": position.get("last_v9_decision"),
                "last_v9_evidence_hash": position.get("last_v9_evidence_hash"),
                "last_v9_reasons": position.get("last_v9_reasons") or [],
                "reason": "OK_REAL_MARK" if available else "MISSING_REAL_MARK",
            }
        )
    read_status = str(market_marks.get("read_status") or "UNKNOWN")
    return {
        "read_only": True,
        "external_action": False,
        "endpoint": market_marks.get("endpoint"),
        "request_type": market_marks.get("request_type"),
        "read_status": read_status,
        "latest_mark_age_ms": _mark_age_ms(market_marks, current_ms),
        "marks_used": marks_used,
        "marks_missing": marks_missing,
        "invalid_positions_skipped": len(invalid_positions or []),
        "invalid_positions": (invalid_positions or [])[:10],
        "positions": per_position,
        "graph_should_move": marks_used > 0,
        "flat_graph_reason": None if marks_used > 0 else _flat_graph_reason(read_status, marks_missing),
    }


def _flat_graph_reason(read_status: str, marks_missing: int) -> str:
    if marks_missing > 0:
        return "NO_REAL_MARK_FOR_OPEN_POSITION"
    if read_status == "NO_OPEN_POSITION":
        return "NO_OPEN_PAPER_POSITION"
    return read_status or "NO_REAL_MARK"


def _copy_position_quality_exit_reason(position: dict[str, Any], *, current_ms: int, min_age_ms: int) -> str:
    mode = str(position.get("position_mode") or "").upper()
    family = str(position.get("strategy_family") or "").lower()
    strategy_id = str(position.get("strategy_id") or position.get("wallet_address") or "").lower()
    raw = f"{mode} {family} {strategy_id}"
    copy_like = (
        "EXTERNAL_GITHUB_COPY_PAPER" in mode
        or "EXTERNAL_GITHUB_FUSION_PAPER" in mode
        or "FUSION_PAPER" in mode
        or "COPY_FOLLOW" in mode
        or any(token in raw for token in ("copy", "whale", "mirror", "autonomous_sltp", "direction_hunt"))
    )
    if not copy_like:
        return ""
    opened_at = _safe_int(position.get("opened_at_ms")) or 0
    if opened_at and current_ms - opened_at < int(min_age_ms):
        return ""
    missing: list[str] = []
    edge = _safe_float(position.get("edge_remaining_bps"))
    age_ms = _safe_float(position.get("signal_age_ms"))
    leader_wallets = _safe_int(position.get("leader_wallets_count"))
    if leader_wallets is None:
        leader_wallets = _csv_count(position.get("leader_wallets_csv"))
    liquidity = _safe_float(position.get("liquidity_score"))
    if edge is None:
        missing.append("edge_remaining_bps")
    if age_ms is None:
        missing.append("signal_age_ms")
    if leader_wallets < 2:
        missing.append("leader_wallets_count>=2")
    if liquidity is None:
        missing.append("liquidity_score")
    if not missing:
        return ""
    return "QUALITY_GUARD_LEGACY_UNEVIDENCED_POSITION_CLOSED_LOCAL_REPLAY_NOT_AN_ORDER:" + ",".join(missing)


def _normalize_position_for_status(raw_position: dict[str, Any], *, index: int) -> dict[str, Any]:
    coin = _infer_status_coin(raw_position, index=index) or "UNKNOWN"
    direction = str(raw_position.get("direction") or raw_position.get("side") or "").upper()
    raw_size = _safe_float(raw_position.get("size")) or 0.0
    if direction not in {"LONG", "SHORT"}:
        direction = "SHORT" if raw_size < 0 else "LONG"
    size = abs(raw_size)
    entry_price = (
        _safe_float(raw_position.get("avg_price"))
        or _safe_float(raw_position.get("avg_entry_price"))
        or _safe_float(raw_position.get("entry_price"))
        or 0.0
    )
    leader_wallets = _csv_count(raw_position.get("leader_wallets_csv"))
    if leader_wallets <= 0:
        leader_wallets = _safe_int(raw_position.get("leader_wallets_count")) or _safe_int(raw_position.get("wallet_count")) or 1
    wallet = str(raw_position.get("wallet_address") or raw_position.get("leader_wallet") or "")
    return {
        "position_id": str(raw_position.get("position_id") or raw_position.get("source_delta_key") or f"position:{index}"),
        "wallet_address": wallet,
        "coin": coin,
        "market": coin,
        "market_id": coin,
        "direction": direction,
        "side": direction,
        "size": round(size, 12),
        "entry_price": round(entry_price, 8),
        "avg_entry_price": round(entry_price, 8),
        "opened_at_ms": _safe_int(raw_position.get("opened_at_ms")) or 0,
        "last_update_at_ms": _safe_int(raw_position.get("last_update_at_ms")) or 0,
        "position_mode": str(raw_position.get("position_mode") or "SINGLE_LEADER"),
        "strategy_id": str(raw_position.get("strategy_id") or ""),
        "strategy_family": str(raw_position.get("strategy_family") or ""),
        "leader_wallets_count": leader_wallets,
        "wallet_count": leader_wallets,
        "edge_remaining_bps": _safe_float(raw_position.get("edge_remaining_bps")),
        "signal_age_ms": _safe_float(raw_position.get("signal_age_ms")),
        "liquidity_score": _safe_float(raw_position.get("liquidity_score")),
        "copy_degradation_bps": _safe_float(raw_position.get("copy_degradation_bps")),
        "quality_evidence_missing": bool(
            _copy_position_quality_exit_reason(raw_position, current_ms=now_ms(), min_age_ms=0)
        ),
        "source_delta_key": str(raw_position.get("source_delta_key") or ""),
        "last_replay_action": str(raw_position.get("last_replay_action") or ""),
        "last_evidence_hash": str(raw_position.get("last_evidence_hash") or ""),
        "last_paper_ref": str(raw_position.get("last_paper_ref") or ""),
        "last_v9_decision": str(raw_position.get("last_v9_decision") or ""),
        "last_v9_evidence_hash": str(raw_position.get("last_v9_evidence_hash") or ""),
        "last_v9_reasons": raw_position.get("last_v9_reasons") or [],
        "last_reduce_fraction": round(_safe_float(raw_position.get("last_reduce_fraction")) or 0.0, 6),
        "last_notional_closed_usdt": round(_safe_float(raw_position.get("last_notional_closed_usdt")) or 0.0, 6),
        "entry_count": _safe_int(raw_position.get("entry_count")) or 0,
        "increase_count": _safe_int(raw_position.get("increase_count")) or 0,
        "reduce_count": _safe_int(raw_position.get("reduce_count")) or 0,
    }


_BAD_STATUS_COIN_TOKENS = {
    "LONG",
    "SHORT",
    "BUY",
    "SELL",
    "OPEN",
    "CLOSE",
    "REDUCE",
    "INCREASE",
    "ADD",
    "POSITION",
    "FUSION",
    "RUNTIME",
    "PAPER",
    "ENGINE",
    "UNKNOWN",
    "NONE",
    "NULL",
}


def _infer_status_coin(raw_position: dict[str, Any], *, index: int) -> str:
    """Infer the Hyperliquid coin without ever inventing a market.

    Some older/local paper adapters keyed positions as
    ``wallet|BTC|LONG`` or ``fusion-runtime:...:PAXG:SHORT:...`` while the row
    itself did not always keep ``coin`` populated. The UI must never display
    ``?`` as a tradable market; this helper recovers a clear coin when present
    and otherwise returns an empty string so the row can be skipped honestly.
    """

    del index  # reserved for future diagnostics without changing call sites
    for key in ("coin", "market", "market_id", "asset", "symbol", "base_coin"):
        coin = _clean_status_coin(raw_position.get(key))
        if coin:
            return coin
    for key in (
        "position_id",
        "source_delta_key",
        "last_paper_ref",
        "matched_position_key",
        "id",
        "strategy_id",
    ):
        text = str(raw_position.get(key) or "")
        if not text:
            continue
        for token in re.split(r"[^A-Za-z0-9@#]+", text.upper()):
            coin = _clean_status_coin(token)
            if coin:
                return coin
    return ""


def _clean_status_coin(value: object) -> str:
    raw = str(value or "").strip().upper()
    if not raw or raw in {"?", "--", "-", "N/A"}:
        return ""
    if raw.startswith("0X") and len(raw) > 10:
        return ""
    for suffix in ("-USD", "-USDT", "/USD", "/USDT", "_USD", "_USDT"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    if raw in _BAD_STATUS_COIN_TOKENS:
        return ""
    if len(raw) > 24:
        return ""
    if not re.fullmatch(r"[@#]?[A-Z0-9:]{1,24}", raw):
        return ""
    return raw


def _is_valid_status_position(position: dict[str, Any]) -> bool:
    coin = _clean_status_coin(position.get("coin"))
    direction = str(position.get("direction") or position.get("side") or "").upper()
    size = _safe_float(position.get("size")) or 0.0
    entry = _safe_float(position.get("entry_price")) or 0.0
    return bool(coin and direction in {"LONG", "SHORT"} and abs(size) > 0.0 and entry > 0.0)


def _append_fast_equity_point(
    settings: Settings | None,
    state: UiState,
    marked: dict[str, Any],
    current_ms: int,
) -> None:
    point = {
        "timestamp_ms": current_ms,
        "current_pnl_usdc": float(marked.get("estimated_net_pnl_usdc") or 0.0),
        "current_equity_usdt": float(marked.get("current_equity_usdt") or 0.0),
        "realized_pnl_usdc": float(marked.get("realized_pnl_usdc") or 0.0),
        "unrealized_pnl_usdc": float(marked.get("unrealized_pnl_usdc") or 0.0),
        "open_exposure_usdt": float(marked.get("open_exposure_usdt") or 0.0),
        "open_positions": len(marked.get("positions") or []),
        "market_marks_used": int(marked.get("marks_used") or 0),
        "market_marks_missing": int(marked.get("marks_missing") or 0),
        "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
    }
    history = getattr(state, "simulation_equity_history", None)
    if not isinstance(history, list):
        state.simulation_equity_history = []
        history = state.simulation_equity_history
    _drop_legacy_overview_equity_points(history)
    _dedupe_equity_history_timestamps(history)
    if history and isinstance(history[-1], dict):
        last = history[-1]
        last_ts = _safe_int(last.get("timestamp_ms")) or 0
        last_source = str(last.get("source") or "")
        unchanged = all(
            abs(float(point[key]) - float(last.get(key) or 0.0)) < 1e-9
            for key in ("current_pnl_usdc", "current_equity_usdt", "realized_pnl_usdc", "unrealized_pnl_usdc", "open_exposure_usdt")
        ) and int(point.get("open_positions") or 0) == int(last.get("open_positions") or 0)
        if current_ms <= last_ts and last_source != "SESSION_START":
            point["timestamp_ms"] = last_ts
            if unchanged:
                return
            history[-1] = point
            if settings is not None:
                try:
                    persist_simulation_state(settings, state)
                except OSError:
                    _noter_echec("hl_observer/ui/status_routes.py:1800")
            return
        if 0 <= current_ms - last_ts < FAST_STATUS_PERSIST_MIN_MS and last_source != "SESSION_START":
            point["timestamp_ms"] = current_ms
            if unchanged:
                return
            history[-1] = point
            if settings is not None:
                try:
                    persist_simulation_state(settings, state)
                except OSError:
                    _noter_echec("hl_observer/ui/status_routes.py:1811")
            return
    history.append(point)
    history[:] = history[-5_000:]
    if settings is None:
        return
    try:
        persist_simulation_state(settings, state)
    except OSError:
        return


def _drop_legacy_overview_equity_points(history: list[dict[str, Any]]) -> None:
    """Keep the live graph on one mark-to-market convention.

    The heavy overview endpoint historically appended MARK_TO_MARKET points
    with a different position/exposure convention than the lightweight status
    endpoint. Mixing both in the same series created the visible spike-then-drop
    effect in simulation_v2.html. Once the fast Hyperliquid status tick is
    available, remove those legacy overview points and let this endpoint be the
    sole live graph writer.
    """

    history[:] = [
        point
        for point in history
        if not (
            isinstance(point, dict)
            and str(point.get("source") or "") == "MARK_TO_MARKET"
        )
    ]


def _dedupe_equity_history_timestamps(history: list[dict[str, Any]]) -> None:
    """Remove graph artifacts caused by multiple equity values at the same ms."""

    cleaned: list[dict[str, Any]] = []
    for point in history:
        if not isinstance(point, dict):
            continue
        point_ts = _safe_int(point.get("timestamp_ms"))
        if point_ts is None:
            continue
        if cleaned:
            last_ts = _safe_int(cleaned[-1].get("timestamp_ms")) or 0
            if point_ts == last_ts:
                cleaned[-1] = point
                continue
            if point_ts < last_ts:
                point = dict(point)
                point["timestamp_ms"] = last_ts + 1
        cleaned.append(point)
    if len(cleaned) != len(history) or any(
        a is not b for a, b in zip(cleaned, history, strict=False)
    ):
        history[:] = cleaned[-5_000:]


def _csv_count(value: object) -> int:
    if not value:
        return 0
    return len([item for item in str(value).split(",") if item.strip()])


def _scanner_payload_from_engine_status(engine_status: dict[str, Any], current_ms: int) -> dict[str, Any]:
    updated_at_ms = _safe_int(engine_status.get("updated_at_ms"))
    heartbeat_age_ms = current_ms - updated_at_ms if updated_at_ms is not None else None
    phase = str(engine_status.get("phase") or "unknown")
    engine_running = bool(
        engine_status.get("available")
        and heartbeat_age_ms is not None
        and 0 <= heartbeat_age_ms <= ENGINE_HEARTBEAT_STALE_MS
        and phase != "finished"
    )
    metrics = engine_status.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    leaders_selected = _metric_int(metrics, "leaders_selected", "selected_top_wallets", "fresh_leaders_selected")
    fresh_leaders_selected = _metric_int(metrics, "fresh_leaders_selected")
    wallet_candidates_total = _metric_int(metrics, "wallet_candidates_total", "public_trade_candidates")
    public_trade_events = _metric_int(metrics, "fresh_public_trade_events", "public_trade_events")
    position_deltas_total = _metric_int(metrics, "position_deltas_total", "recent_deltas")
    fresh_entry_deltas = _metric_int(metrics, "fresh_entry_deltas")
    virtual_entries = _metric_int(metrics, "virtual_entries_logged")
    virtual_refusals = _metric_int(metrics, "virtual_refusals_logged")
    entry_supply = _entry_supply_status(
        wallet_candidates_total=wallet_candidates_total,
        public_trade_events=public_trade_events,
        position_deltas_total=position_deltas_total,
        fresh_entry_deltas=fresh_entry_deltas,
        virtual_entries=virtual_entries,
        virtual_refusals=virtual_refusals,
    )
    return {
        "engine_running": engine_running,
        "heartbeat_age_ms": heartbeat_age_ms,
        "phase": phase,
        "message": str(engine_status.get("message") or ""),
        "poll_index": _safe_int(engine_status.get("poll_index")) or 0,
        "max_runs": _safe_int(engine_status.get("max_runs")) or 0,
        "pool": _safe_int(engine_status.get("pool")) or 0,
        "leaders_per_poll": _safe_int(engine_status.get("leaders_per_poll")) or 0,
        "leaders_selected": leaders_selected,
        "fresh_leaders_selected": fresh_leaders_selected,
        "wallet_candidates_total": wallet_candidates_total,
        "public_trade_events": public_trade_events,
        "position_deltas_total": position_deltas_total,
        "fresh_entry_deltas": fresh_entry_deltas,
        "virtual_entries_logged": virtual_entries,
        "virtual_refusals_logged": virtual_refusals,
        "entry_supply": entry_supply,
        "entry_supply_bottleneck": entry_supply["bottleneck"],
        "entry_supply_next_action": entry_supply["next_action"],
        "entry_supply_summary": entry_supply["summary"],
        "read_only": bool(engine_status.get("read_only", True)),
        "simulation_only": bool(engine_status.get("simulation_only", True)),
        "external_action": bool(engine_status.get("external_action", False)),
    }


def _entry_supply_status(
    *,
    wallet_candidates_total: int,
    public_trade_events: int,
    position_deltas_total: int,
    fresh_entry_deltas: int,
    virtual_entries: int,
    virtual_refusals: int,
) -> dict[str, Any]:
    """Explain why the paper bot is or is not opening positions.

    This deliberately stays diagnostic-only. It does not loosen gates and does
    not fabricate trades; it just separates a data-supply problem from a
    risk/edge-gate problem for the UI and logs.
    """

    observed_context = max(0, wallet_candidates_total) + max(0, public_trade_events) + max(0, position_deltas_total)
    fresh_entries = max(0, fresh_entry_deltas)
    entries = max(0, virtual_entries)
    refusals = max(0, virtual_refusals)
    if entries > 0:
        bottleneck = BOTTLENECK_OK
        severity = "ok"
        summary = "Position paper ouverte sur un signal accepte."
        next_action = "Suivre le mark-to-market, les sorties leader et le PnL realise."
    elif observed_context <= 0:
        bottleneck = BOTTLENECK_NO_DATA
        severity = "error"
        summary = "Aucune donnee exploitable recue par le moteur."
        next_action = "Verifier que le lanceur, le WS public et la collecte /info tournent."
    elif fresh_entries <= 0:
        bottleneck = BOTTLENECK_SUPPLY
        severity = "warning"
        summary = "Le moteur voit du flux, mais pas assez d'entrees leader fraiches."
        next_action = "Augmenter la source fraiche: WS leaders chauds, refresh shortlist, collecte publique."
    else:
        bottleneck = BOTTLENECK_GATES
        severity = "warning"
        summary = "Des entrees fraiches existent, mais les gates edge/risque/liquidite refusent."
        next_action = "Analyser les raisons de refus avant de calibrer edge, liquidite, spread ou sizing."
    return {
        "bottleneck": bottleneck,
        "severity": severity,
        "summary": summary,
        "next_action": next_action,
        "observed_context": observed_context,
        "fresh_entry_deltas": fresh_entries,
        "virtual_entries_logged": entries,
        "virtual_refusals_logged": refusals,
    }


def _metric_int(metrics: dict[str, Any], *names: str) -> int:
    for name in names:
        value = _safe_int(metrics.get(name))
        if value is not None:
            return value
    return 0


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
