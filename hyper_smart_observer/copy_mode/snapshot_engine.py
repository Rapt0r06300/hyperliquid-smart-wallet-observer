from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_models import FillView, PositionView, stable_hash, utc_now
from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.hyperliquid_client.normalization import NormalizationError, normalize_position_snapshot, normalize_user_fill
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address
from hyper_smart_observer.storage.repositories import fills_repo, positions_repo, wallet_repo


class InfoClientLike(Protocol):
    def get_all_mids(self) -> dict[str, Any]: ...

    def get_clearinghouse_state(self, address: str) -> dict[str, Any]: ...

    def collect_user_fills_by_time_paginated(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        max_pages: int | None = None,
    ): ...

    def get_user_fills(self, address: str, *, aggregate_by_time: bool = False) -> list[dict[str, Any]]: ...

    def get_open_orders(self, address: str) -> list[dict[str, Any]]: ...

    def get_frontend_open_orders(self, address: str) -> list[dict[str, Any]]: ...

    def get_user_fees(self, address: str) -> dict[str, Any]: ...

    def get_user_rate_limit(self, address: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LeaderSnapshot:
    snapshot_id: str
    wallet_address: str
    captured_at: datetime
    positions: list[PositionView]
    fills: list[FillView]
    open_orders: list[dict[str, Any]]
    frontend_open_orders: list[dict[str, Any]]
    all_mids: dict[str, Any]
    collection_run_id: str
    leader_account_value: float | None = None
    fills_cursor: str | None = None
    stopped_reason: str = "completed"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CollectionRun:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "RUNNING"
    stopped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def start_collection_run(conn: sqlite3.Connection, source: str = "copy_run") -> CollectionRun:
    run = CollectionRun(run_id="run:" + stable_hash(f"{source}:{utc_now().isoformat()}")[:24], started_at=utc_now())
    conn.execute(
        """
        INSERT OR REPLACE INTO collection_runs(run_id, source, started_at, finished_at, status, stopped_reason, warnings_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run.run_id, source, run.started_at.isoformat(), None, run.status, run.stopped_reason, "[]"),
    )
    return run


def finish_collection_run(
    conn: sqlite3.Connection,
    run: CollectionRun,
    *,
    status: str,
    stopped_reason: str,
    warnings: list[str] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET finished_at = ?, status = ?, stopped_reason = ?, warnings_json = ?
        WHERE run_id = ?
        """,
        (utc_now().isoformat(), status, stopped_reason, json.dumps(warnings or run.warnings), run.run_id),
    )


def collect_leader_snapshot(
    *,
    config: AppConfig,
    conn: sqlite3.Connection,
    info_client: InfoClientLike,
    wallet_address: str,
    start_time_ms: int,
    end_time_ms: int,
    all_mids: dict[str, Any],
    collection_run_id: str,
) -> LeaderSnapshot:
    wallet = normalize_wallet_address(wallet_address)
    captured_at = utc_now()
    warnings: list[str] = []
    wallet_repo.insert_wallet(conn, Wallet(address=wallet, source="copy_run"))
    clearinghouse = info_client.get_clearinghouse_state(wallet)
    leader_account_value = _extract_account_value(clearinghouse)
    raw_positions = clearinghouse.get("assetPositions") or clearinghouse.get("positions") or []
    positions = []
    for raw_position in raw_positions:
        try:
            snapshot = normalize_position_snapshot(raw_position, wallet)
        except NormalizationError as exc:
            warnings.append(f"position_skipped:{exc}")
            continue
        positions_repo.insert_position_snapshot(conn, snapshot)
        positions.append(
            PositionView(
                wallet_address=wallet,
                coin=snapshot.coin,
                signed_size=snapshot.size,
                timestamp=snapshot.timestamp,
                mark_price=snapshot.mark_price,
            )
        )
    paginated = info_client.collect_user_fills_by_time_paginated(
        wallet,
        start_time_ms,
        end_time_ms,
        max_pages=config.max_pages_per_wallet,
    )
    recent_fills = []
    try:
        recent_fills = info_client.get_user_fills(wallet)
    except Exception as exc:  # read-only diagnostics, caller records health
        warnings.append(f"user_fills_recent_failed:{exc}")
    raw_fills = list(paginated.fills)
    known = {_fill_dedupe_key(item, wallet) for item in raw_fills}
    raw_fills.extend(item for item in recent_fills if _fill_dedupe_key(item, wallet) not in known)
    fills: list[FillView] = []
    for raw_fill in raw_fills[: config.max_fills_per_run]:
        dedupe_key = _fill_dedupe_key(raw_fill, wallet)
        if _dedupe_seen(conn, dedupe_key):
            warnings.append("duplicate_fill_skipped")
            continue
        try:
            fill = normalize_user_fill(raw_fill, wallet)
        except NormalizationError as exc:
            warnings.append(f"fill_skipped:{exc}")
            continue
        fills_repo.insert_fill(conn, fill)
        _insert_fill_snapshot(conn, fill, raw_fill, dedupe_key, collection_run_id)
        fills.append(
            FillView(
                wallet_address=wallet,
                coin=fill.coin,
                direction=fill.action_type or fill.side,
                side=fill.side,
                size=fill.size,
                price=fill.price,
                start_position=fill.start_position,
                closed_pnl=fill.closed_pnl,
                timestamp=fill.timestamp,
                raw_id=fill.raw_id,
            )
        )
    open_orders = info_client.get_open_orders(wallet)
    frontend_open_orders = info_client.get_frontend_open_orders(wallet)
    try:
        info_client.get_user_fees(wallet)
        _write_api_health(conn, "userFees", True, "read-only user fees checked")
    except Exception as exc:
        warnings.append(f"user_fees_failed:{exc}")
        _write_api_health(conn, "userFees", False, str(exc))
    try:
        info_client.get_user_rate_limit(wallet)
        _write_api_health(conn, "userRateLimit", True, "read-only user rate limit checked")
    except Exception as exc:
        warnings.append(f"user_rate_limit_failed:{exc}")
        _write_api_health(conn, "userRateLimit", False, str(exc))
    snapshot_id = "snap:" + stable_hash(f"{wallet}:{captured_at.isoformat()}:{collection_run_id}")[:24]
    _insert_open_order_snapshots(conn, wallet, open_orders, captured_at, "openOrders")
    _insert_open_order_snapshots(conn, wallet, frontend_open_orders, captured_at, "frontendOpenOrders")
    conn.execute(
        """
        INSERT OR REPLACE INTO leader_snapshots(
            snapshot_id, wallet_address, captured_at, source, positions_json, fills_cursor,
            open_orders_json, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            wallet,
            captured_at.isoformat(),
            "hyperliquid_info",
            json.dumps([position.__dict__ | {"timestamp": position.timestamp.isoformat() if position.timestamp else None} for position in positions]),
            str(end_time_ms + 1),
            json.dumps({"openOrders": open_orders, "frontendOpenOrders": frontend_open_orders}, sort_keys=True),
            json.dumps([*warnings, f"pagination:{paginated.stopped_reason}"]),
        ),
    )
    _write_source_health(conn, "hyperliquid_info", "OK", f"snapshot stored; pagination={paginated.stopped_reason}")
    return LeaderSnapshot(
        snapshot_id=snapshot_id,
        wallet_address=wallet,
        captured_at=captured_at,
        positions=positions,
        fills=fills,
        open_orders=open_orders,
        frontend_open_orders=frontend_open_orders,
        all_mids=all_mids,
        collection_run_id=collection_run_id,
        leader_account_value=leader_account_value,
        fills_cursor=str(end_time_ms + 1),
        stopped_reason=paginated.stopped_reason,
        warnings=[*warnings, *paginated.warnings],
    )


def latest_previous_positions(conn: sqlite3.Connection, wallet_address: str, before: datetime) -> list[PositionView]:
    rows = conn.execute(
        """
        SELECT * FROM position_snapshots
        WHERE wallet_address = ? AND timestamp < ?
        ORDER BY timestamp DESC
        """,
        (wallet_address.lower(), before.isoformat()),
    ).fetchall()
    seen: set[str] = set()
    positions: list[PositionView] = []
    for row in rows:
        coin = str(row["coin"]).upper()
        if coin in seen:
            continue
        seen.add(coin)
        positions.append(
            PositionView(
                wallet_address=row["wallet_address"],
                coin=coin,
                signed_size=float(row["size"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                mark_price=row["mark_price"],
            )
        )
    return positions


def _fill_dedupe_key(raw_fill: dict[str, Any], wallet: str) -> str:
    raw_id = raw_fill.get("hash") or raw_fill.get("tid") or raw_fill.get("oid")
    payload = f"{wallet}:{raw_fill.get('coin')}:{raw_id}:{raw_fill.get('time') or raw_fill.get('timestamp')}:{raw_fill.get('px') or raw_fill.get('price')}:{raw_fill.get('sz') or raw_fill.get('size')}"
    return "fill:" + stable_hash(payload)[:32]


def _extract_account_value(clearinghouse: dict[str, Any]) -> float | None:
    margin = clearinghouse.get("marginSummary") or clearinghouse.get("crossMarginSummary") or {}
    value = margin.get("accountValue") if isinstance(margin, dict) else None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dedupe_seen(conn: sqlite3.Connection, dedupe_key: str) -> bool:
    if conn.execute("SELECT 1 FROM fill_dedupe WHERE dedupe_key = ?", (dedupe_key,)).fetchone():
        return True
    return False


def _insert_fill_snapshot(conn: sqlite3.Connection, fill, raw_fill: dict[str, Any], dedupe_key: str, collection_run_id: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO fill_dedupe(dedupe_key, wallet_address, coin, fill_time, raw_id, seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (dedupe_key, fill.wallet_address, fill.coin, fill.timestamp.isoformat(), fill.raw_id, utc_now().isoformat()),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO fill_snapshots(
            snapshot_id, wallet_address, coin, fill_time, raw_id, direction, side, price, size,
            closed_pnl, start_position, source, collection_run_id, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fs:" + stable_hash(f"{dedupe_key}:{collection_run_id}")[:24],
            fill.wallet_address,
            fill.coin,
            fill.timestamp.isoformat(),
            fill.raw_id,
            fill.action_type,
            fill.side,
            fill.price,
            fill.size,
            fill.closed_pnl,
            fill.start_position,
            fill.source,
            collection_run_id,
            json.dumps(raw_fill, sort_keys=True),
        ),
    )


def _insert_open_order_snapshots(
    conn: sqlite3.Connection,
    wallet: str,
    orders: list[dict[str, Any]],
    captured_at: datetime,
    source: str,
) -> None:
    for index, order in enumerate(orders):
        conn.execute(
            """
            INSERT OR REPLACE INTO open_order_snapshots(snapshot_id, wallet_address, coin, captured_at, raw_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "oo:" + stable_hash(f"{wallet}:{source}:{captured_at.isoformat()}:{index}:{order}")[:24],
                wallet,
                str(order.get("coin") or "").upper() or None,
                captured_at.isoformat(),
                json.dumps({"source": source, "payload": order}, sort_keys=True),
            ),
        )


def _write_source_health(conn: sqlite3.Connection, source: str, status: str, message: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO source_health(source, checked_at, status, message, failures_count)
        VALUES (?, ?, ?, ?, COALESCE((SELECT failures_count FROM source_health WHERE source = ?), 0) + ?)
        """,
        (source, utc_now().isoformat(), status, message, source, 0 if status == "OK" else 1),
    )


def _write_api_health(conn: sqlite3.Connection, component: str, ok: bool, message: str) -> None:
    conn.execute(
        """
        INSERT INTO api_health(component, checked_at, ok, message)
        VALUES (?, ?, ?, ?)
        """,
        (component, utc_now().isoformat(), 1 if ok else 0, message),
    )
