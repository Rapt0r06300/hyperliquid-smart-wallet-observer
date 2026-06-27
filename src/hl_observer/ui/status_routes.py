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

import json
import os
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
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import MarketSnapshot
from hl_observer.ui.persistent_state import persist_simulation_state, simulation_state_path
from hl_observer.ui.state import UiState
from hl_observer.ui.v12_status_provider import build_v12_status_payload
from hl_observer.utils.time import now_ms


ENGINE_STATUS_FILENAME = "hypersmart_engine_status.json"
ENGINE_HEARTBEAT_STALE_MS = 45_000
MARK_SNAPSHOT_LIMIT = 60
FAST_STATUS_EXIT_COST_BPS = 12.0
FAST_STATUS_PERSIST_MIN_MS = 900
LIVE_MARKS_MIN_INTERVAL_MS = 850
LIVE_MARKS_MAX_STALE_MS = 5_000
LIVE_MARKS_TIMEOUT_SECONDS = 0.9


def create_status_router(state: UiState, settings: Settings | None = None) -> APIRouter:
    router = APIRouter()
    cached_session_factory: Any = None
    live_mark_cache: dict[str, Any] = {
        "fetched_at_ms": 0,
        "prices": {},
        "error": None,
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
        return {
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
            "positions": marked["positions"],
            "mark_to_market": marked["mark_to_market"],
            "mark_diagnostics": marked["mark_diagnostics"],
            "v12": build_v12_status_payload(engine_status=engine_status, scanner=scanner),
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
            },
            "counts": {},
            "message": "Paper local, donnees Hyperliquid reelles. No order, no key, no signature.",
        }

    return router


def _engine_status_path(settings: Settings | None) -> Path:
    if settings is not None:
        try:
            return simulation_state_path(settings).parent / ENGINE_STATUS_FILENAME
        except Exception:  # noqa: BLE001 - status endpoint must never fail on path resolution.
            pass
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
        str(row.get("coin") or row.get("market") or row.get("market_id") or "").upper()
        for row in raw_positions
        if isinstance(row, dict)
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
    for index, raw_position in enumerate(raw_positions):
        normalized = _normalize_position_for_status(raw_position, index=index)
        coin = normalized["coin"]
        direction = normalized["direction"]
        size = abs(float(normalized["size"]))
        entry_price = float(normalized["entry_price"])
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
            "cost_model_bps": FAST_STATUS_EXIT_COST_BPS,
            "no_fallback_position_created": True,
            "official_simulation": "simulation_v2.html",
            "heartbeat_is_diagnostic_only": True,
        },
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


def _normalize_position_for_status(raw_position: dict[str, Any], *, index: int) -> dict[str, Any]:
    coin = str(raw_position.get("coin") or raw_position.get("market") or raw_position.get("market_id") or "?").upper()
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
        "leader_wallets_count": leader_wallets,
        "wallet_count": leader_wallets,
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
    if history and isinstance(history[-1], dict):
        last = history[-1]
        last_ts = _safe_int(last.get("timestamp_ms")) or 0
        if current_ms - last_ts < FAST_STATUS_PERSIST_MIN_MS and all(
            abs(float(point[key]) - float(last.get(key) or 0.0)) < 1e-9
            for key in ("current_pnl_usdc", "current_equity_usdt", "realized_pnl_usdc", "unrealized_pnl_usdc", "open_exposure_usdt")
        ):
            return
    history.append(point)
    history[:] = history[-5_000:]
    if settings is None:
        return
    try:
        persist_simulation_state(settings, state)
    except OSError:
        return


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
