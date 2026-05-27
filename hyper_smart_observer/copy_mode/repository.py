from __future__ import annotations

import json
import sqlite3

from hyper_smart_observer.copy_mode.copy_models import LeaderShortlistEntry, NoTradeDecision, SignalCandidate, to_jsonable


def insert_shortlist_entries(conn: sqlite3.Connection, entries: list[LeaderShortlistEntry]) -> None:
    for entry in entries:
        conn.execute(
            """
            INSERT OR REPLACE INTO leaderboard_shortlist(
                wallet_address, status, score, source, rank, history_days, closed_pnl_points,
                pnl_concentration, consistency_score, max_drawdown_pct, refusal_reasons_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.wallet_address,
                entry.status.value,
                entry.score,
                entry.source,
                entry.rank,
                entry.history_days,
                entry.closed_pnl_points,
                entry.pnl_concentration,
                entry.consistency_score,
                entry.max_drawdown_pct,
                json.dumps(entry.refusal_reasons),
                json.dumps(entry.warnings),
            ),
        )


def insert_signal_candidate(conn: sqlite3.Connection, signal: SignalCandidate) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO copy_signal_candidates(
            candidate_id, leader_wallet, coin, action_type, observed_at, leader_fill_time,
            leader_reference_price, current_mid, spread_bps, slippage_bps, fee_bps, latency_ms,
            liquidity_score, leader_score, signal_freshness_score, copy_degradation_bps,
            edge_remaining_bps, paper_mode, decision, refusal_reasons_json, raw_event_hash,
            source_snapshot_id, collection_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal.candidate_id,
            signal.leader_wallet,
            signal.coin,
            signal.action_type.value,
            signal.observed_at.isoformat(),
            signal.leader_fill_time.isoformat() if signal.leader_fill_time else None,
            signal.leader_reference_price,
            signal.current_mid,
            signal.spread_bps,
            signal.slippage_bps,
            signal.fee_bps,
            signal.latency_ms,
            signal.liquidity_score,
            signal.leader_score,
            signal.signal_freshness_score,
            signal.copy_degradation_bps,
            signal.edge_remaining_bps,
            signal.paper_mode,
            signal.decision.value,
            json.dumps(signal.refusal_reasons),
            signal.raw_event_hash,
            signal.source_snapshot_id,
            signal.collection_run_id,
        ),
    )


def insert_no_trade_decision(conn: sqlite3.Connection, decision: NoTradeDecision) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO no_trade_decisions(
            decision_id, created_at, reason, observed, why_not_simulable, missing_data,
            next_action, leader_wallet, coin, candidate_id, risk_level, component, context_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.decision_id,
            decision.created_at.isoformat(),
            decision.reason.value,
            decision.observed,
            decision.why_not_simulable,
            decision.missing_data,
            decision.next_action,
            decision.leader_wallet,
            decision.coin,
            decision.candidate_id,
            decision.risk_level,
            decision.component,
            json.dumps(to_jsonable(decision.context), sort_keys=True),
        ),
    )


def insert_leader_delta(conn: sqlite3.Connection, delta) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO leader_deltas(
            delta_id, leader_wallet, coin, action_type, observed_at, previous_size, current_size,
            leader_reference_price, leader_fill_time, raw_event_hash, source_snapshot_id,
            collection_run_id, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            delta.delta_id,
            delta.leader_wallet,
            delta.coin,
            delta.action_type.value,
            delta.observed_at.isoformat(),
            delta.previous_size,
            delta.current_size,
            delta.leader_reference_price,
            delta.leader_fill_time.isoformat() if delta.leader_fill_time else None,
            delta.raw_event_hash,
            delta.source_snapshot_id,
            delta.collection_run_id,
            json.dumps(delta.warnings),
        ),
    )


def list_latest_leader_deltas(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM leader_deltas ORDER BY observed_at DESC LIMIT ?",
            (limit,),
        )
    )


def list_latest_signal_candidates(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM copy_signal_candidates ORDER BY observed_at DESC LIMIT ?",
            (limit,),
        )
    )


def list_no_trade_decisions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM no_trade_decisions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )


def list_shortlist(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM leaderboard_shortlist ORDER BY status = 'SHORTLISTED' DESC, score DESC LIMIT ?",
            (limit,),
        )
    )
