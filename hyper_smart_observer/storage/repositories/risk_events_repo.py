from __future__ import annotations

import json
import sqlite3

from hyper_smart_observer.hyperliquid_client.models import RiskEvent


def insert_risk_event(conn: sqlite3.Connection, event: RiskEvent) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO risk_events(
            event_id, created_at, severity, component, reason_code, message, blocked_action, context_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.created_at.isoformat(),
            event.severity,
            event.component,
            event.reason_code,
            event.message,
            event.blocked_action,
            json.dumps(event.context, sort_keys=True),
        ),
    )


def list_risk_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM risk_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    )
