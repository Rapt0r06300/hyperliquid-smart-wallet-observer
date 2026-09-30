from __future__ import annotations

import sqlite3

from hyper_smart_observer.hyperliquid_client.models import PositionSnapshot


def insert_position_snapshot(conn: sqlite3.Connection, snapshot: PositionSnapshot) -> None:
    conn.execute(
        """
        INSERT INTO position_snapshots(
            wallet_address, coin, size, entry_price, mark_price, unrealized_pnl, leverage, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.wallet_address.lower(),
            snapshot.coin.upper(),
            snapshot.size,
            snapshot.entry_price,
            snapshot.mark_price,
            snapshot.unrealized_pnl,
            snapshot.leverage,
            snapshot.timestamp.isoformat(),
        ),
    )


def insert_many_position_snapshots(conn: sqlite3.Connection, snapshots: list[PositionSnapshot]) -> int:
    before = conn.total_changes
    for snapshot in snapshots:
        insert_position_snapshot(conn, snapshot)
    return conn.total_changes - before


def list_position_snapshots_for_wallet(
    conn: sqlite3.Connection,
    wallet_address: str,
    limit: int = 100,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM position_snapshots
            WHERE wallet_address = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (wallet_address.lower(), limit),
        )
    )
