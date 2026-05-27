from __future__ import annotations

import sqlite3

from hyper_smart_observer.hyperliquid_client.models import Wallet, WalletStatus


def insert_wallet(conn: sqlite3.Connection, wallet: Wallet) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO wallets(address, label, source, discovered_at, status, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            wallet.address.lower(),
            wallet.label,
            wallet.source,
            wallet.discovered_at.isoformat(),
            wallet.status.value,
            wallet.notes,
        ),
    )


def get_wallet(conn: sqlite3.Connection, address: str) -> Wallet | None:
    row = conn.execute("SELECT * FROM wallets WHERE address = ?", (address.lower(),)).fetchone()
    if row is None:
        return None
    return Wallet(
        address=row["address"],
        label=row["label"],
        source=row["source"],
        status=WalletStatus(row["status"]),
        notes=row["notes"],
    )


def list_wallets(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM wallets ORDER BY discovered_at DESC LIMIT ?", (limit,)))
