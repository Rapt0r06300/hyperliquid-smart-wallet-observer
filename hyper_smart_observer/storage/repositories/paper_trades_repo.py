from __future__ import annotations

import json
import sqlite3

from hyper_smart_observer.hyperliquid_client.models import (
    PaperIntent,
    PaperIntentStatus,
    PaperTrade,
    PaperTradeStatus,
)


def insert_paper_intent(conn: sqlite3.Connection, intent: PaperIntent) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_intents(
            intent_id, wallet_address, coin, side, reference_price, requested_notional,
            created_at, source, reason, score_snapshot_id, status, refusal_reason, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            intent.intent_id,
            intent.wallet_address.lower(),
            intent.coin.upper(),
            intent.side.upper(),
            intent.reference_price,
            intent.requested_notional,
            intent.created_at.isoformat(),
            intent.source,
            intent.reason,
            intent.score_snapshot_id,
            intent.status.value,
            intent.refusal_reason,
            json.dumps(intent.warnings),
        ),
    )


def update_paper_intent_status(
    conn: sqlite3.Connection,
    intent_id: str,
    status: PaperIntentStatus,
    reason: str | None = None,
) -> None:
    conn.execute(
        "UPDATE paper_intents SET status = ?, refusal_reason = COALESCE(?, refusal_reason) WHERE intent_id = ?",
        (status.value, reason, intent_id),
    )


def insert_paper_trade(conn: sqlite3.Connection, trade: PaperTrade) -> None:
    _ensure_legacy_signal_if_needed(conn, trade)
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_trades(
            trade_id, signal_id, intent_id, wallet_address, coin, side, entry_price, exit_price,
            size, notional, simulated_fee, simulated_slippage, fee_entry, fee_exit,
            slippage_entry, slippage_exit, spread_cost, opened_at, closed_at, pnl,
            gross_pnl, net_pnl, state, status, close_reason, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.trade_id,
            trade.signal_id,
            trade.intent_id,
            trade.wallet_address.lower() if trade.wallet_address else None,
            trade.coin.upper(),
            trade.side.upper(),
            trade.entry_price,
            trade.exit_price,
            trade.size,
            trade.notional,
            trade.simulated_fee,
            trade.simulated_slippage,
            trade.fee_entry,
            trade.fee_exit,
            trade.slippage_entry,
            trade.slippage_exit,
            trade.spread_cost,
            trade.opened_at.isoformat(),
            trade.closed_at.isoformat() if trade.closed_at else None,
            trade.pnl,
            trade.gross_pnl,
            trade.net_pnl,
            trade.state,
            trade.status.value if hasattr(trade.status, "value") else str(trade.status),
            trade.close_reason,
            json.dumps(trade.warnings),
        ),
    )


def update_paper_trade_close(
    conn: sqlite3.Connection,
    *,
    trade_id: str,
    exit_price: float,
    fee_exit: float,
    slippage_exit: float,
    spread_cost: float,
    closed_at: str,
    gross_pnl: float,
    net_pnl: float,
    close_reason: str,
) -> None:
    conn.execute(
        """
        UPDATE paper_trades
        SET exit_price = ?, fee_exit = ?, slippage_exit = ?, spread_cost = ?,
            closed_at = ?, gross_pnl = ?, net_pnl = ?, pnl = ?,
            state = 'CLOSED', status = ?, close_reason = ?
        WHERE trade_id = ?
        """,
        (
            exit_price,
            fee_exit,
            slippage_exit,
            spread_cost,
            closed_at,
            gross_pnl,
            net_pnl,
            net_pnl,
            PaperTradeStatus.CLOSED.value,
            close_reason,
            trade_id,
        ),
    )


def update_paper_trade_after_partial(
    conn: sqlite3.Connection,
    *,
    trade_id: str,
    remaining_size: float,
    remaining_notional: float,
    remaining_simulated_fee: float,
    remaining_simulated_slippage: float,
    remaining_fee_entry: float,
    remaining_slippage_entry: float,
    remaining_spread_cost: float,
) -> None:
    conn.execute(
        """
        UPDATE paper_trades
        SET size = ?, notional = ?, simulated_fee = ?, simulated_slippage = ?,
            fee_entry = ?, slippage_entry = ?, spread_cost = ?,
            state = 'OPEN', status = ?
        WHERE trade_id = ?
        """,
        (
            remaining_size,
            remaining_notional,
            remaining_simulated_fee,
            remaining_simulated_slippage,
            remaining_fee_entry,
            remaining_slippage_entry,
            remaining_spread_cost,
            PaperTradeStatus.OPEN.value,
            trade_id,
        ),
    )


def get_paper_trade(conn: sqlite3.Connection, trade_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM paper_trades WHERE trade_id = ?", (trade_id,)).fetchone()


def list_open_paper_trades(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM paper_trades WHERE COALESCE(status, state) = 'OPEN' ORDER BY opened_at ASC"
        )
    )


def list_closed_paper_trades(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM paper_trades
            WHERE COALESCE(status, state) = 'CLOSED'
            ORDER BY closed_at DESC LIMIT ?
            """,
            (limit,),
        )
    )


def list_paper_intents(
    conn: sqlite3.Connection, limit: int = 50, status: str | None = None
) -> list[sqlite3.Row]:
    params: list[object] = []
    where = ""
    if status:
        where = "WHERE status = ?"
        params.append(status)
    params.append(limit)
    return list(
        conn.execute(
            f"SELECT * FROM paper_intents {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
    )


def _ensure_legacy_signal_if_needed(conn: sqlite3.Connection, trade: PaperTrade) -> None:
    if not _has_legacy_signal_fk(conn):
        return
    wallet_address = trade.wallet_address or "0x" + "0" * 40
    conn.execute(
        """
        INSERT OR IGNORE INTO wallets(address, label, source, discovered_at, status, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            wallet_address.lower(),
            "paper-compat",
            "paper_trading",
            trade.opened_at.isoformat(),
            "OBSERVED",
            "Compatibility wallet for local paper simulation.",
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO signals(signal_id, wallet_address, coin, side, confidence, created_at, state, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.signal_id,
            wallet_address.lower(),
            trade.coin.upper(),
            trade.side.upper(),
            0.0,
            trade.opened_at.isoformat(),
            "PAPER_ACCEPTED",
            "local paper simulation compatibility row; not a trading signal",
        ),
    )


def _has_legacy_signal_fk(conn: sqlite3.Connection) -> bool:
    return any(row["table"] == "signals" for row in conn.execute("PRAGMA foreign_key_list(paper_trades)"))
