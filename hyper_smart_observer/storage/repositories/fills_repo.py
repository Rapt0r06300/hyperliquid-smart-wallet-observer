from __future__ import annotations

import sqlite3

from hyper_smart_observer.hyperliquid_client.models import Fill


def insert_fill(conn: sqlite3.Connection, fill: Fill) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO fills(
            wallet_address, coin, side, price, size, fee, timestamp, raw_id, source, closed_pnl,
            action_type, start_position, fee_token, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fill.wallet_address.lower(),
            fill.coin.upper(),
            fill.side,
            fill.price,
            fill.size,
            fill.fee,
            fill.timestamp.isoformat(),
            fill.raw_id,
            fill.source,
            fill.closed_pnl,
            fill.action_type,
            fill.start_position,
            fill.fee_token,
            fill.raw_json,
        ),
    )


def list_fills_for_wallet(conn: sqlite3.Connection, wallet_address: str, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM fills WHERE wallet_address = ? ORDER BY timestamp DESC LIMIT ?",
            (wallet_address.lower(), limit),
        )
    )


def list_all_fills_for_wallet(
    conn: sqlite3.Connection, wallet_address: str, limit: int | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM fills WHERE wallet_address = ? ORDER BY timestamp ASC"
    params: tuple[object, ...]
    if limit is not None:
        sql += " LIMIT ?"
        params = (wallet_address.lower(), limit)
    else:
        params = (wallet_address.lower(),)
    return list(conn.execute(sql, params))


def insert_many_fills(conn: sqlite3.Connection, fills: list[Fill]) -> int:
    before = conn.total_changes
    for fill in fills:
        insert_fill(conn, fill)
    return conn.total_changes - before


def list_fills_for_period(
    conn: sqlite3.Connection,
    wallet_address: str,
    start_iso: str,
    end_iso: str,
    limit: int = 1000,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM fills
            WHERE wallet_address = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC LIMIT ?
            """,
            (wallet_address.lower(), start_iso, end_iso, limit),
        )
    )
