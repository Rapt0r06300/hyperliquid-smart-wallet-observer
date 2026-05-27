from __future__ import annotations

import sqlite3

from hyper_smart_observer.hyperliquid_client.models import Signal


def insert_signal(conn: sqlite3.Connection, signal: Signal) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO signals(signal_id, wallet_address, coin, side, confidence, created_at, state, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal.signal_id,
            signal.wallet_address.lower(),
            signal.coin.upper(),
            signal.side,
            signal.confidence,
            signal.created_at.isoformat(),
            signal.state.value,
            signal.reason,
        ),
    )
