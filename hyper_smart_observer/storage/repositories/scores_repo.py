from __future__ import annotations

import json
import sqlite3

from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, WalletScore


def insert_wallet_score(conn: sqlite3.Connection, score: WalletScore) -> None:
    conn.execute(
        """
        INSERT INTO wallet_scores(
            wallet_address, calculated_at, total_trades, winrate, pnl_net, max_drawdown,
            profit_factor, sharpe, sortino, calmar, confidence_score, final_score, refusal_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            score.wallet_address.lower(),
            score.calculated_at.isoformat(),
            score.total_trades,
            score.winrate,
            score.pnl_net,
            score.max_drawdown,
            score.profit_factor,
            score.sharpe,
            score.sortino,
            score.calmar,
            score.confidence_score,
            score.final_score,
            score.refusal_reason,
        ),
    )


def insert_score_breakdown(conn: sqlite3.Connection, score: ScoreBreakdown) -> None:
    conn.execute(
        """
        INSERT INTO wallet_scores(
            wallet_address, calculated_at, status, total_trades, usable_fills, skipped_fills,
            first_fill_at, last_fill_at, history_days, gross_pnl, net_pnl, total_fees,
            winrate, average_win, average_loss, pnl_net, max_drawdown, profit_factor,
            sharpe, sortino, calmar, sample_quality_score, recency_score, consistency_score,
            risk_score, confidence_score, final_score, refusal_reason, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            score.wallet_address.lower(),
            score.calculated_at.isoformat(),
            score.status.value,
            score.total_fills,
            score.usable_fills,
            score.skipped_fills,
            score.first_fill_at.isoformat() if score.first_fill_at else None,
            score.last_fill_at.isoformat() if score.last_fill_at else None,
            score.history_days,
            score.gross_pnl,
            score.net_pnl,
            score.total_fees,
            score.winrate,
            score.average_win,
            score.average_loss,
            score.net_pnl,
            score.max_drawdown,
            score.profit_factor,
            score.sharpe,
            score.sortino,
            score.calmar,
            score.sample_quality_score,
            score.recency_score,
            score.consistency_score,
            score.risk_score,
            score.confidence_score,
            score.final_score,
            score.refusal_reason,
            json.dumps(score.warnings),
        ),
    )


def get_latest_score(conn: sqlite3.Connection, wallet_address: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM wallet_scores
        WHERE wallet_address = ?
        ORDER BY calculated_at DESC, id DESC
        LIMIT 1
        """,
        (wallet_address.lower(),),
    ).fetchone()


def list_latest_scores(
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
            f"""
            SELECT * FROM wallet_scores
            {where}
            ORDER BY calculated_at DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        )
    )


def list_rejected_scores(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM wallet_scores
            WHERE status IS NOT NULL AND status != 'SCORED'
            ORDER BY calculated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
    )
