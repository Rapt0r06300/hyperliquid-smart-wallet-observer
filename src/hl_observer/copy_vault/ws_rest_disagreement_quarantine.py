"""[COPY-VAULT lot2 #50] WS/REST DISAGREEMENT QUARANTINE : tant qu'une divergence entre la vue WS et la vue REST
d'un vault n'est pas RÉSOLUE, AUCUN OPEN/ADD n'est autorisé (on ne prend pas de nouveau risque sur un état
contradictoire). Les réductions restent permises (réduire le risque est toujours sûr). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class Quarantaine:
    """Marque un vault en quarantaine tant qu'un désaccord WS/REST n'est pas levé. Bloque OPEN/ADD, pas REDUCE/CLOSE."""

    def __init__(self, *, tolerance: float = 1e-6) -> None:
        self.tolerance = float(tolerance)
        self._quarantaine: set[str] = set()

    def evaluer(self, vault: str, *, valeur_ws: Any, valeur_rest: Any) -> dict[str, Any]:
        """Met en quarantaine si |ws − rest| > tolérance ou données manquantes ; sinon lève la quarantaine."""
        if not all(isinstance(x, (int, float)) for x in (valeur_ws, valeur_rest)):
            self._quarantaine.add(str(vault))
            return {"quarantaine": True, "raison": "DONNEE_MANQUANTE"}
        if abs(float(valeur_ws) - float(valeur_rest)) > self.tolerance:
            self._quarantaine.add(str(vault))
            return {"quarantaine": True, "raison": "DIVERGENCE_WS_REST"}
        self._quarantaine.discard(str(vault))
        return {"quarantaine": False, "raison": "ACCORD_WS_REST"}

    def peut_open_add(self, vault: str) -> dict[str, Any]:
        bloque = str(vault) in self._quarantaine
        return {"peut_open_add": (not bloque), "peut_reduce": True,
                "raison": ("OK" if not bloque else "QUARANTAINE_WS_REST")}


def reconciliation_receipt(*, valeur_ws: Any, valeur_rest: Any, tolerance: float = 1e-6) -> dict[str, Any]:
    """Produce a fail-closed reconciliation decision before any new exposure."""

    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (valeur_ws, valeur_rest, tolerance)) or float(tolerance) < 0:
        return {"status": "UNMEASURABLE", "open_allowed": False, "reason": "RECONCILIATION_INVALID", "paper_read_only": True}
    reconciled = abs(float(valeur_ws) - float(valeur_rest)) <= float(tolerance)
    return {"status": "PROVEN", "open_allowed": reconciled,
            "reason": "AGREE" if reconciled else "DIVERGENCE_QUARANTINED", "paper_read_only": True}


def quarantine_event_contract_receipt(row: dict[str, Any]) -> dict[str, Any]:
    required = ("vault", "source", "event_id", "source_ts_ms", "receive_ts_ms")
    valid = isinstance(row, dict) and all(str(row.get(field) or "").strip() for field in required) and all(isinstance(row.get(field), int) and not isinstance(row.get(field), bool) for field in ("source_ts_ms", "receive_ts_ms"))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_EVENT_COMPLETE" if valid else "QUARANTINE_EVENT_INVALID", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_required_field_receipt(row: dict[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, dict) and field in row and row[field] not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_FIELD_PRESENT" if valid else "QUARANTINE_FIELD_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_finite_receipt(value: Any) -> dict[str, Any]:
    try:
        parsed = float(value); valid = parsed == parsed and abs(parsed) != float("inf")
    except (TypeError, ValueError, OverflowError):
        parsed = None; valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_FINITE" if valid else "QUARANTINE_NON_FINITE", "value": parsed if valid else None, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(cutoff_ts_ms, int) and not isinstance(event_ts_ms, bool) and not isinstance(cutoff_ts_ms, bool) and event_ts_ms <= cutoff_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_CUTOFF_VALID" if valid else "QUARANTINE_CUTOFF_BREACH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = isinstance(event_ts_ms, int) and isinstance(oldest_allowed_ts_ms, int) and not isinstance(event_ts_ms, bool) and not isinstance(oldest_allowed_ts_ms, bool) and event_ts_ms >= oldest_allowed_ts_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_AGE_VALID" if valid else "QUARANTINE_EVENT_TOO_OLD", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_duplicate_receipt(*, event_ids: list[str]) -> dict[str, Any]:
    valid = bool(event_ids) and len(event_ids) == len(set(event_ids)) and all(event_ids)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_IDS_UNIQUE" if valid else "QUARANTINE_DUPLICATE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_retry_receipt(*, attempts: int, max_attempts: int, checkpoint_saved: bool) -> dict[str, Any]:
    valid = isinstance(attempts, int) and isinstance(max_attempts, int) and 1 <= attempts <= max_attempts and bool(checkpoint_saved)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_RETRY_BOUNDED" if valid else "QUARANTINE_RETRY_UNSAFE", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "QUARANTINE_REPLAY_DETERMINISTIC" if valid else "QUARANTINE_REPLAY_DIVERGED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def rest_ws_fill_receipt(*, ws_identity: str, rest_identity: str) -> dict[str, Any]:
    valid = bool(ws_identity) and ws_identity == rest_identity
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "REST_WS_FILL_MATCH" if valid else "REST_WS_FILL_DIVERGENCE", "open_allowed": valid, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def same_timestamp_quarantine_receipt(*, identities: list[str]) -> dict[str, Any]:
    valid = bool(identities) and len(identities) == len(set(identities))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SAME_TIMESTAMP_DISTINCT" if valid else "SAME_TIMESTAMP_COLLISION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_tid_receipt(row: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, dict) and row.get("tid") not in (None, "")
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "TID_PRESENT" if valid else "TID_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_hash_receipt(row: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, dict) and len(str(row.get("hash") or "")) >= 8
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "HASH_PRESENT" if valid else "HASH_MISSING", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_close_open_receipt(*, open_ids: list[str], close_ids: list[str]) -> dict[str, Any]:
    valid = bool(close_ids) and set(close_ids).issubset(set(open_ids))
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "CLOSE_HAS_OPEN" if valid else "CLOSE_WITHOUT_OPEN", "open_allowed": False, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_wallet_receipt(*, expected_wallet: str, observed_wallet: str) -> dict[str, Any]:
    valid = bool(expected_wallet) and expected_wallet == observed_wallet
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "WALLET_MATCH" if valid else "WALLET_MISMATCH", "open_allowed": valid, "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_side_receipt(*, declared_side: str, source_side: str) -> dict[str, Any]:
    valid = declared_side in {"buy", "sell"} and declared_side == source_side
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "SIDE_MATCH" if valid else "SIDE_CONTRADICTION", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_backfill_receipt(*, existing_ids: list[str], backfill_ids: list[str], overlap_analyzed: bool) -> dict[str, Any]:
    overlap = set(existing_ids) & set(backfill_ids); valid = not overlap or bool(overlap_analyzed)
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "BACKFILL_OVERLAP_BOUND" if valid else "BACKFILL_OVERLAP_UNANALYZED", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_position_receipt(*, position_delta: float, fill_deltas: list[float], tolerance: float = 1e-9) -> dict[str, Any]:
    try:
        valid = abs(float(position_delta) - sum(float(value) for value in fill_deltas)) <= tolerance
    except (TypeError, ValueError):
        valid = False
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "POSITION_MATCHES_FILLS" if valid else "POSITION_FILL_MISMATCH", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


def quarantine_heartbeat_receipt(*, previous_ts_ms: Any, current_ts_ms: Any, max_gap_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (previous_ts_ms, current_ts_ms, max_gap_ms)) and 0 <= current_ts_ms - previous_ts_ms <= max_gap_ms
    return {"status": "PROVEN" if valid else "REJECTED", "verdict": "HEARTBEAT_CONTINUOUS" if valid else "HEARTBEAT_GAP", "paper_read_only": True, "real_execution": False, "fail_closed": not valid}


__all__ = ["Quarantaine", "reconciliation_receipt", "quarantine_event_contract_receipt", "quarantine_required_field_receipt", "quarantine_finite_receipt", "quarantine_cutoff_receipt", "quarantine_age_receipt", "quarantine_duplicate_receipt", "quarantine_retry_receipt", "quarantine_replay_receipt", "rest_ws_fill_receipt", "same_timestamp_quarantine_receipt", "quarantine_tid_receipt", "quarantine_hash_receipt", "quarantine_close_open_receipt", "quarantine_wallet_receipt", "quarantine_side_receipt", "quarantine_backfill_receipt", "quarantine_position_receipt", "quarantine_heartbeat_receipt"]
