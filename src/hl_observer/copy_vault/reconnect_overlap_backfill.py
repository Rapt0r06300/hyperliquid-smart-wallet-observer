"""[COPY-VAULT lot2 #37] RECONNECT OVERLAP BACKFILL : après une reconnexion, on demande VOLONTAIREMENT une fenêtre
de backfill qui commence AVANT le dernier checkpoint (chevauchement), pour détecter les événements manqués juste
avant la coupure. Reprendre pile au checkpoint laisserait un trou si un événement est arrivé pendant la bascule.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def fenetre_backfill(dernier_checkpoint_ms: Any, *, overlap_ms: float = 5000.0) -> dict[str, Any]:
    """Renvoie le début de la fenêtre de backfill = checkpoint − overlap (jamais après le checkpoint).
    Checkpoint invalide → UNMEASURABLE."""
    if not isinstance(dernier_checkpoint_ms, (int, float)):
        return {"debut_ms": UNMEASURABLE, "raison": "CHECKPOINT_INVALIDE"}
    debut = float(dernier_checkpoint_ms) - abs(float(overlap_ms))
    return {"debut_ms": round(debut, 3), "checkpoint_ms": float(dernier_checkpoint_ms),
            "overlap_ms": abs(float(overlap_ms)), "raison": "FENETRE_AVEC_CHEVAUCHEMENT"}


def reconnect_contract_receipt(row: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, dict) and all(str(row.get(field) or "").strip() for field in ("connection_id", "checkpoint_id", "event_id")) and isinstance(row.get("receive_ts_ms"), int) and row.get("receive_ts_ms") >= 0
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_CONTRACT_COMPLETE" if valid else "RECONNECT_CONTRACT_INVALID", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_required_field_receipt(row: dict[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, dict) and field in row and row[field] not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_FIELD_PRESENT" if valid else "RECONNECT_FIELD_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_finite_receipt(value: Any) -> dict[str, Any]:
    try:
        parsed = float(value); valid = parsed == parsed and abs(parsed) != float("inf")
    except (TypeError, ValueError, OverflowError):
        parsed = None; valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_FINITE" if valid else "RECONNECT_NON_FINITE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(cutoff_ts_ms, int) and event_ts_ms <= cutoff_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_CUTOFF_VALID" if valid else "RECONNECT_CUTOFF_BREACH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(oldest_allowed_ts_ms, int) and event_ts_ms >= oldest_allowed_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_AGE_VALID" if valid else "RECONNECT_EVENT_TOO_OLD", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_duplicate_receipt(*, event_ids: list[str]) -> dict[str, Any]:
    valid = bool(event_ids) and len(event_ids) == len(set(event_ids)) and all(event_ids)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_IDS_UNIQUE" if valid else "RECONNECT_DUPLICATE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_retry_receipt(*, attempts: int, max_attempts: int, checkpoint_saved: bool) -> dict[str, Any]:
    valid = isinstance(attempts, int) and isinstance(max_attempts, int) and 1 <= attempts <= max_attempts and bool(checkpoint_saved)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_RETRY_BOUNDED" if valid else "RECONNECT_RETRY_UNSAFE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_REPLAY_DETERMINISTIC" if valid else "RECONNECT_REPLAY_DIVERGED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_rest_ws_receipt(*, ws_identity: str, rest_identity: str) -> dict[str, Any]:
    valid = bool(ws_identity) and ws_identity == rest_identity
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_REST_WS_MATCH" if valid else "RECONNECT_REST_WS_DIVERGENCE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_timestamp_identity_receipt(*, identities: list[str]) -> dict[str, Any]:
    valid = bool(identities) and len(identities) == len(set(identities))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_TIMESTAMP_DISTINCT" if valid else "RECONNECT_TIMESTAMP_COLLISION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_tid_receipt(row: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, dict) and row.get("tid") not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_TID_PRESENT" if valid else "RECONNECT_TID_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_hash_receipt(row: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, dict) and len(str(row.get("hash") or "")) >= 8
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_HASH_PRESENT" if valid else "RECONNECT_HASH_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_close_open_receipt(*, open_ids: list[str], close_ids: list[str]) -> dict[str, Any]:
    valid = bool(close_ids) and set(close_ids).issubset(set(open_ids))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_CLOSE_HAS_OPEN" if valid else "RECONNECT_CLOSE_WITHOUT_OPEN", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_wallet_receipt(*, expected_wallet: str, observed_wallet: str) -> dict[str, Any]:
    valid = bool(expected_wallet) and expected_wallet == observed_wallet
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_WALLET_MATCH" if valid else "RECONNECT_WALLET_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_side_receipt(*, declared_side: str, source_side: str) -> dict[str, Any]:
    valid = declared_side in {"buy", "sell"} and declared_side == source_side
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_SIDE_MATCH" if valid else "REJECTED_SIDE_CONTRADICTION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_overlap_receipt(*, checkpoint_ms: Any, backfill_start_ms: Any, overlap_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, (int, float)) for value in (checkpoint_ms, backfill_start_ms, overlap_ms)) and overlap_ms > 0 and backfill_start_ms < checkpoint_ms and abs((checkpoint_ms - backfill_start_ms) - overlap_ms) <= 1e-6
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "BACKFILL_OVERLAP_EXPLICIT" if valid else "BACKFILL_OVERLAP_INVALID", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_position_receipt(*, position_delta: float, fill_deltas: list[float], tolerance: float = 1e-9) -> dict[str, Any]:
    try:
        valid = abs(float(position_delta) - sum(float(value) for value in fill_deltas)) <= tolerance
    except (TypeError, ValueError):
        valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_POSITION_MATCH" if valid else "RECONNECT_POSITION_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def reconnect_heartbeat_receipt(*, previous_ts_ms: Any, current_ts_ms: Any, max_gap_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) for value in (previous_ts_ms, current_ts_ms, max_gap_ms)) and 0 <= current_ts_ms - previous_ts_ms <= max_gap_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "RECONNECT_HEARTBEAT_CONTINUOUS" if valid else "RECONNECT_HEARTBEAT_GAP", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


__all__ = ["fenetre_backfill", "UNMEASURABLE", "reconnect_contract_receipt", "reconnect_required_field_receipt", "reconnect_finite_receipt", "reconnect_cutoff_receipt", "reconnect_age_receipt", "reconnect_duplicate_receipt", "reconnect_retry_receipt", "reconnect_replay_receipt", "reconnect_rest_ws_receipt", "reconnect_timestamp_identity_receipt", "reconnect_tid_receipt", "reconnect_hash_receipt", "reconnect_close_open_receipt", "reconnect_wallet_receipt", "reconnect_side_receipt", "reconnect_overlap_receipt", "reconnect_position_receipt", "reconnect_heartbeat_receipt"]
