"""Small SQLite persistence layer for V12 research artifacts.

This module is intentionally separate from the legacy SQLAlchemy model file so
V12 slices can persist useful evidence without risky wide migrations. It creates
only additive ``v12_*`` tables and uses idempotent upserts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


DDL = (
    """
    CREATE TABLE IF NOT EXISTS v12_wallet_scores (
        wallet TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        copyability_score REAL NOT NULL,
        sample_confidence REAL NOT NULL,
        reasons_json TEXT NOT NULL,
        score_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at_ms INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v12_signal_clusters (
        cluster_id TEXT PRIMARY KEY,
        coin TEXT NOT NULL,
        side TEXT NOT NULL,
        accepted INTEGER NOT NULL,
        consensus_strength REAL NOT NULL,
        reason_codes_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        observed_at_ms INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v12_edge_estimates (
        estimate_id TEXT PRIMARY KEY,
        measurable INTEGER NOT NULL,
        accepted INTEGER NOT NULL,
        net_edge_bps REAL,
        reason_codes_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at_ms INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v12_decision_evidence (
        evidence_hash TEXT PRIMARY KEY,
        decision_id TEXT,
        accepted INTEGER NOT NULL,
        reason_codes_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at_ms INTEGER NOT NULL
    )
    """,
)


class V12SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self.connect() as conn:
            for ddl in DDL:
                conn.execute(ddl)
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000")
        if self.path != Path(":memory:"):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def upsert_wallet_score(self, score: Any, *, updated_at_ms: int) -> None:
        payload = _payload(score)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO v12_wallet_scores
                (wallet, status, copyability_score, sample_confidence, reasons_json, score_hash, payload_json, updated_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("wallet"),
                    payload.get("status"),
                    float(payload.get("copyability_score", 0.0)),
                    float(payload.get("sample_confidence", 0.0)),
                    _json(payload.get("reasons", [])),
                    payload.get("score_hash", ""),
                    _json(payload),
                    int(updated_at_ms),
                ),
            )
            conn.commit()

    def upsert_signal_cluster(self, cluster: Any) -> None:
        payload = _payload(cluster)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO v12_signal_clusters
                (cluster_id, coin, side, accepted, consensus_strength, reason_codes_json, payload_json, observed_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("cluster_id"),
                    payload.get("coin"),
                    payload.get("side"),
                    1 if payload.get("accepted") else 0,
                    float(payload.get("consensus_strength", 0.0)),
                    _json(payload.get("reason_codes", [])),
                    _json(payload),
                    int(payload.get("observed_at_ms", 0)),
                ),
            )
            conn.commit()

    def upsert_edge_estimate(self, estimate_id: str, estimate: Any, *, created_at_ms: int) -> None:
        payload = _payload(estimate)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO v12_edge_estimates
                (estimate_id, measurable, accepted, net_edge_bps, reason_codes_json, payload_json, created_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    estimate_id,
                    1 if payload.get("measurable") else 0,
                    1 if payload.get("accepted") else 0,
                    payload.get("net_edge_bps"),
                    _json(payload.get("reason_codes", [])),
                    _json(payload),
                    int(created_at_ms),
                ),
            )
            conn.commit()

    def upsert_decision_evidence(self, evidence: Any, *, created_at_ms: int) -> None:
        payload = _payload(evidence)
        evidence_hash = payload.get("evidence_hash")
        if not evidence_hash:
            raise ValueError("evidence_hash is required")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO v12_decision_evidence
                (evidence_hash, decision_id, accepted, reason_codes_json, payload_json, created_at_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_hash,
                    payload.get("decision_id"),
                    1 if payload.get("accepted") else 0,
                    _json(payload.get("reason_codes", [])),
                    _json(payload),
                    int(created_at_ms),
                ),
            )
            conn.commit()

    def count(self, table_name: str) -> int:
        if table_name not in {
            "v12_wallet_scores",
            "v12_signal_clusters",
            "v12_edge_estimates",
            "v12_decision_evidence",
        }:
            raise ValueError(f"unsupported table: {table_name}")
        with self.connect() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def latest(self, table_name: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if table_name not in {
            "v12_wallet_scores",
            "v12_signal_clusters",
            "v12_edge_estimates",
            "v12_decision_evidence",
        }:
            raise ValueError(f"unsupported table: {table_name}")
        order_col = {
            "v12_wallet_scores": "updated_at_ms",
            "v12_signal_clusters": "observed_at_ms",
            "v12_edge_estimates": "created_at_ms",
            "v12_decision_evidence": "created_at_ms",
        }[table_name]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY {order_col} DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]


def _payload(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        maybe = value.to_dict()
        if isinstance(maybe, dict):
            return maybe
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"unsupported payload type: {type(value)!r}")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = ["V12SQLiteStore"]
