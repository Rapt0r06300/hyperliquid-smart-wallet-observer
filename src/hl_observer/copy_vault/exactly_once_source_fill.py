"""[COPY-VAULT #60] EXACTLY-ONCE SOURCE FILL : chaque fill source est identifié de façon unique par
(wallet + tid/hash + oid), de sorte qu'un même fill ne soit consommé qu'UNE fois — même s'il arrive deux fois
(rejeu WS, double flux). C'est l'index d'unicité qui garantit l'exactly-once côté ingestion. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from collections.abc import Mapping
from typing import Any


def identite(*, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> str:
    """Clé d'identité d'un fill. Au moins un discriminant (tid/oid/hash) requis en plus du wallet."""
    # Keep the field name and the value length in the key.  Joining values only
    # made ``tid=1`` collide with ``oid=1`` and allowed delimiter-containing
    # values to produce ambiguous identities.
    parts = []
    for name, value in (("tid", tid), ("oid", oid), ("hash", hash_)):
        if value is None:
            continue
        text = str(value)
        parts.append(f"{name}:{len(text)}:{text}")
    return "%s#%s" % (str(wallet).lower(), "|".join(parts))


class RegistreFills:
    """Ensemble des identités de fills déjà consommées. `consommer` est idempotent (2e fois → deja_vu)."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._vus: set[str] = set()
        self._storage_error: str | None = None
        self._connection: sqlite3.Connection | None = None
        if storage_path is not None:
            try:
                path = Path(storage_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(str(path), timeout=5.0)
                self._connection.execute("PRAGMA busy_timeout = 5000")
                self._connection.execute("PRAGMA synchronous = FULL")
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS fills_seen ("
                    "identity TEXT PRIMARY KEY NOT NULL)"
                )
                self._connection.commit()
            except (OSError, sqlite3.Error) as exc:
                self._storage_error = type(exc).__name__
                if self._connection is not None:
                    self._connection.close()
                self._connection = None

    def deja_vu(self, cle: str) -> bool:
        key = str(cle)
        if self._connection is None:
            return key in self._vus
        try:
            row = self._connection.execute(
                "SELECT 1 FROM fills_seen WHERE identity = ?", (key,)
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def consommer(self, *, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> dict[str, Any]:
        """Marque le fill consommé. Refuse (nouveau=False) si l'identité a déjà été vue. Aucun discriminant →
        refus (on ne consomme jamais un fill non identifiable, il pourrait être un doublon)."""
        if tid is None and oid is None and hash_ is None:
            return {"nouveau": False, "raison": "FILL_NON_IDENTIFIABLE"}
        cle = identite(wallet=wallet, tid=tid, oid=oid, hash_=hash_)
        if self._storage_error is not None:
            return {
                "nouveau": False,
                "cle": cle,
                "raison": "REGISTRE_DURABILITE_INDISPONIBLE",
            }
        if self._connection is not None:
            try:
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO fills_seen(identity) VALUES (?)", (cle,)
                )
                self._connection.commit()
                if cursor.rowcount != 1:
                    return {"nouveau": False, "cle": cle, "raison": "DEJA_CONSOMME"}
                return {"nouveau": True, "cle": cle, "raison": "OK"}
            except sqlite3.Error as exc:
                self._storage_error = type(exc).__name__
                return {
                    "nouveau": False,
                    "cle": cle,
                    "raison": "REGISTRE_DURABILITE_INDISPONIBLE",
                }
        if cle in self._vus:
            return {"nouveau": False, "cle": cle, "raison": "DEJA_CONSOMME"}
        self._vus.add(cle)
        return {"nouveau": True, "cle": cle, "raison": "OK"}

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "RegistreFills":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


def identity_stability_receipt(ws_fill: Mapping[str, Any], rest_fill: Mapping[str, Any]) -> dict[str, Any]:
    """Compare native WS/REST identity and refuse a restart merge when it is missing."""

    if not isinstance(ws_fill, Mapping) or not isinstance(rest_fill, Mapping):
        return {"status": "UNMEASURABLE", "same_identity": False, "reason": "FILL_NOT_MAPPING", "paper_read_only": True}
    ws_key = identite(wallet=ws_fill.get("wallet"), tid=ws_fill.get("tid"), oid=ws_fill.get("oid"), hash_=ws_fill.get("hash"))
    rest_key = identite(wallet=rest_fill.get("wallet"), tid=rest_fill.get("tid"), oid=rest_fill.get("oid"), hash_=rest_fill.get("hash"))
    if all(value is None for value in (ws_fill.get("tid"), ws_fill.get("oid"), ws_fill.get("hash"))):
        return {"status": "UNMEASURABLE", "same_identity": False, "reason": "FILL_NON_IDENTIFIABLE", "paper_read_only": True}
    same = ws_key == rest_key
    return {"status": "PROVEN", "same_identity": same,
            "reason": "SAME_NATIVE_IDENTITY" if same else "IDENTITY_DIVERGENCE",
            "ws_identity": ws_key, "rest_identity": rest_key, "paper_read_only": True}


def source_fill_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    required = ("wallet", "tid", "oid", "hash", "source_ts_ms", "receive_ts_ms")
    valid = isinstance(row, Mapping) and bool(str(row.get("wallet") or "").strip()) and any(row.get(field) not in (None, "") for field in ("tid", "oid", "hash")) and all(isinstance(row.get(field), int) and not isinstance(row.get(field), bool) and row.get(field) >= 0 for field in ("source_ts_ms", "receive_ts_ms"))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_CONTRACT_COMPLETE" if valid else "SOURCE_FILL_CONTRACT_INVALID", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and field in row and row[field] not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_FIELD_PRESENT" if valid else "SOURCE_FILL_FIELD_MISSING", "field": field, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_finite_receipt(value: Any) -> dict[str, Any]:
    try:
        parsed = float(value); valid = parsed == parsed and abs(parsed) != float("inf")
    except (TypeError, ValueError, OverflowError):
        parsed = None; valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_FINITE" if valid else "SOURCE_FILL_NON_FINITE", "value": parsed if valid else None, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(cutoff_ts_ms, int) and not isinstance(event_ts_ms, bool) and not isinstance(cutoff_ts_ms, bool) and event_ts_ms <= cutoff_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_WITHIN_CUTOFF" if valid else "SOURCE_FILL_AFTER_CUTOFF", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(oldest_allowed_ts_ms, int) and not isinstance(event_ts_ms, bool) and not isinstance(oldest_allowed_ts_ms, bool) and event_ts_ms >= oldest_allowed_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_AGE_VALID" if valid else "SOURCE_FILL_TOO_OLD", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_duplicate_receipt(*, identities: list[str]) -> dict[str, Any]:
    valid = bool(identities) and all(identities) and len(identities) == len(set(identities))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_IDENTITIES_UNIQUE" if valid else "SOURCE_FILL_DUPLICATE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_retry_receipt(*, attempts: int, max_attempts: int, checkpoint_saved: bool) -> dict[str, Any]:
    valid = isinstance(attempts, int) and isinstance(max_attempts, int) and 1 <= attempts <= max_attempts and bool(checkpoint_saved)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_RETRY_BOUNDED" if valid else "SOURCE_FILL_RETRY_UNSAFE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def source_fill_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SOURCE_FILL_REPLAY_DETERMINISTIC" if valid else "SOURCE_FILL_REPLAY_DIVERGED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def same_timestamp_fill_receipt(*, fills: list[Mapping[str, Any]]) -> dict[str, Any]:
    identities = [identite(wallet=row.get("wallet"), tid=row.get("tid"), oid=row.get("oid"), hash_=row.get("hash")) for row in fills if isinstance(row, Mapping)]
    valid = len(identities) == len(fills) and len(identities) == len(set(identities))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SAME_TIMESTAMP_FILLS_DISTINCT" if valid else "SAME_TIMESTAMP_FILL_COLLISION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def fill_tid_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and row.get("tid") not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "FILL_TID_PRESENT" if valid else "FILL_TID_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def fill_hash_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and len(str(row.get("hash") or "")) >= 8
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "FILL_HASH_PRESENT" if valid else "FILL_HASH_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def close_open_receipt(*, open_ids: list[str], close_ids: list[str]) -> dict[str, Any]:
    valid = bool(close_ids) and set(close_ids).issubset(set(open_ids))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "CLOSE_HAS_OPEN" if valid else "CLOSE_WITHOUT_OPEN", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def wallet_source_receipt(*, expected_wallet: str, observed_wallet: str) -> dict[str, Any]:
    valid = bool(expected_wallet) and expected_wallet == observed_wallet
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "WALLET_SOURCE_MATCH" if valid else "WALLET_SOURCE_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def side_consistency_receipt(*, declared_side: str, source_side: str) -> dict[str, Any]:
    valid = declared_side in {"buy", "sell"} and declared_side == source_side
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "FILL_SIDE_CONSISTENT" if valid else "FILL_SIDE_CONTRADICTION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def backfill_overlap_receipt(*, existing_ids: list[str], backfill_ids: list[str], overlap_analyzed: bool) -> dict[str, Any]:
    overlap = set(existing_ids) & set(backfill_ids)
    valid = not overlap or bool(overlap_analyzed)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "BACKFILL_OVERLAP_BOUND" if valid else "BACKFILL_OVERLAP_UNANALYZED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def position_fill_consistency_receipt(*, position_delta: float, fill_deltas: list[float], tolerance: float = 1e-9) -> dict[str, Any]:
    try:
        valid = abs(float(position_delta) - sum(float(value) for value in fill_deltas)) <= tolerance
    except (TypeError, ValueError):
        valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "POSITION_MATCHES_FILLS" if valid else "POSITION_FILL_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def heartbeat_continuity_receipt(*, previous_ts_ms: Any, current_ts_ms: Any, max_gap_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (previous_ts_ms, current_ts_ms, max_gap_ms)) and 0 <= current_ts_ms - previous_ts_ms <= max_gap_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "HEARTBEAT_CONTINUOUS" if valid else "HEARTBEAT_GAP", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


__all__ = ["identite", "RegistreFills", "identity_stability_receipt", "source_fill_contract_receipt", "source_fill_required_field_receipt", "source_fill_finite_receipt", "source_fill_cutoff_receipt", "source_fill_age_receipt", "source_fill_duplicate_receipt", "source_fill_retry_receipt", "source_fill_replay_receipt", "same_timestamp_fill_receipt", "fill_tid_receipt", "fill_hash_receipt", "close_open_receipt", "wallet_source_receipt", "side_consistency_receipt", "backfill_overlap_receipt", "position_fill_consistency_receipt", "heartbeat_continuity_receipt"]
