from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any
from hyper_smart_observer.copy_mode.copy_models import (
    LeaderShortlistEntry,
    LeaderDelta,
    SignalCandidate,
    NoTradeDecision,
    to_jsonable
)

def initialize_database(conn: sqlite3.Connection):
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r") as f:
        conn.executescript(f.read())

class UnifiedRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_shortlist_entry(self, entry: LeaderShortlistEntry):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO leader_shortlist (
                wallet_address, status, score, source, rank, history_days,
                closed_pnl_points, pnl_concentration, consistency_score,
                max_drawdown_pct, refusal_reasons_json, warnings_json, last_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                entry.wallet_address.lower(), entry.status.value, entry.score, entry.source,
                entry.rank, entry.history_days, entry.closed_pnl_points, entry.pnl_concentration,
                entry.consistency_score, entry.max_drawdown_pct,
                json.dumps(entry.refusal_reasons), json.dumps(entry.warnings)
            )
        )

    def insert_signal_candidate(self, signal: SignalCandidate):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO signal_candidates (
                candidate_id, leader_wallet, coin, action_type, observed_at,
                edge_remaining_bps, copy_degradation_bps, decision,
                refusal_reasons_json, raw_event_hash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.candidate_id, signal.leader_wallet.lower(), signal.coin.upper(),
                signal.action_type.value, signal.observed_at.isoformat(),
                signal.edge_remaining_bps, signal.copy_degradation_bps,
                signal.decision.value, json.dumps(signal.refusal_reasons),
                signal.raw_event_hash, json.dumps(to_jsonable(signal))
            )
        )

    def insert_no_trade_decision(self, decision: NoTradeDecision):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO no_trade_decisions (
                decision_id, created_at, reason, leader_wallet, coin,
                candidate_id, observed, why_not_simulable, next_action, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id, decision.created_at.isoformat(), decision.reason.value,
                decision.leader_wallet, decision.coin, decision.candidate_id,
                decision.observed, decision.why_not_simulable, decision.next_action,
                json.dumps(decision.context)
            )
        )
