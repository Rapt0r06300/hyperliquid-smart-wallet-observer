"""[COPY-VAULT lot2 #38] GAP DETECTOR BASÉ SUR POSITION : si les fills reçus ne suffisent pas à EXPLIQUER la
nouvelle position du leader (position_après ≠ position_avant + somme des fills), on déclare un GAP — MÊME sans erreur
réseau visible. Un fill manqué se voit à l'incohérence de position, pas seulement à une déconnexion. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math
from typing import Any

_TOL = 1e-6


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def detecter(position_avant: Any, fills_signes: Iterable[Any], position_apres: Any) -> dict[str, Any]:
    """GAP si position_avant + Σ fills ≠ position_apres (à tolérance près). Données invalides → GAP présumé."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, position_apres)):
        return {"gap": True, "raison": "POSITION_INVALIDE"}
    somme = 0.0
    for f in fills_signes:
        if not isinstance(f, (int, float)):
            return {"gap": True, "raison": "FILL_INVALIDE"}
        somme += float(f)
    attendu = float(position_avant) + somme
    ecart = attendu - float(position_apres)
    if abs(ecart) > _TOL:
        return {"gap": True, "ecart": round(ecart, 8), "raison": "FILLS_N_EXPLIQUENT_PAS_LA_POSITION"}
    return {"gap": False, "raison": "POSITION_EXPLIQUEE_PAR_LES_FILLS"}


def gap_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    """Require a causal position/fill observation before treating a gap as measured."""
    valid = (
        isinstance(row, Mapping)
        and _finite(row.get("position_before"))
        and _finite(row.get("position_after"))
        and isinstance(row.get("fills_signed"), Sequence)
        and not isinstance(row.get("fills_signed"), (str, bytes))
        and all(_finite(value) for value in row["fills_signed"])
        and _integer(row.get("event_ts_ms"))
        and _integer(row.get("receive_ts_ms"))
        and row["receive_ts_ms"] >= row["event_ts_ms"]
        and bool(str(row.get("wallet") or "").strip())
    )
    return _base(
        "PROVEN" if valid else "UNMEASURABLE",
        verdict="POSITION_GAP_CONTRACT_COMPLETE" if valid else "POSITION_GAP_CONTRACT_INCOMPLETE",
        fail_closed=not valid,
    )


def gap_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_FIELD_PRESENT" if valid else "GAP_FIELD_MISSING",
        field=field,
        fail_closed=not valid,
    )


def gap_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _finite(value)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_VALUE_FINITE" if valid else "GAP_VALUE_NON_FINITE",
        value=float(value) if valid else None,
        fail_closed=not valid,
    )


def gap_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_EVENT_WITHIN_CUTOFF" if valid else "GAP_EVENT_AFTER_CUTOFF",
        fail_closed=not valid,
    )


def gap_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_EVENT_AGE_VALID" if valid else "GAP_EVENT_TOO_OLD",
        fail_closed=not valid,
    )


def gap_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_EVENTS_UNIQUE" if valid else "GAP_EVENT_DUPLICATE_OR_EMPTY",
        event_count=len(event_ids) if isinstance(event_ids, Sequence) else 0,
        fail_closed=not valid,
    )


def gap_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _integer(attempts) and _integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_RETRY_BOUNDED" if valid else "GAP_RETRY_UNSAFE",
        fail_closed=not valid,
    )


def gap_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_REPLAY_DETERMINISTIC" if valid else "GAP_REPLAY_DIVERGED",
        replay_count=len(outputs) if isinstance(outputs, Sequence) else 0,
        fail_closed=not valid,
    )


def gap_rest_ws_receipt(*, ws_identity: Any, rest_identity: Any) -> dict[str, Any]:
    valid = bool(str(ws_identity or "").strip()) and ws_identity == rest_identity
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_REST_WS_IDENTITY_MATCH" if valid else "GAP_REST_WS_IDENTITY_DIVERGENCE",
        fail_closed=not valid,
    )


def gap_timestamp_identity_receipt(*, identities: Sequence[Any]) -> dict[str, Any]:
    valid = bool(identities) and all(str(value).strip() for value in identities) and len(identities) == len(set(identities))
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_TIMESTAMP_IDENTITIES_STABLE" if valid else "GAP_TIMESTAMP_IDENTITY_COLLISION",
        fail_closed=not valid,
    )


def gap_tid_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and row.get("tid") not in (None, "")
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_TID_PRESENT" if valid else "GAP_TID_MISSING",
        fail_closed=not valid,
    )


def gap_hash_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("hash") if isinstance(row, Mapping) else None
    valid = isinstance(value, str) and len(value) >= 8 and all(character in "0123456789abcdefABCDEF" for character in value)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_HASH_PRESENT" if valid else "GAP_HASH_MISSING_OR_INVALID",
        fail_closed=not valid,
    )


def gap_close_open_receipt(*, open_ids: Sequence[Any], close_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(close_ids) and all(value in set(open_ids) for value in close_ids)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_CLOSE_HAS_OPEN" if valid else "GAP_CLOSE_WITHOUT_OPEN",
        fail_closed=not valid,
    )


def gap_wallet_receipt(*, expected_wallet: Any, observed_wallet: Any) -> dict[str, Any]:
    valid = bool(str(expected_wallet or "").strip()) and expected_wallet == observed_wallet
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_WALLET_MATCH" if valid else "GAP_WALLET_MISMATCH",
        fail_closed=not valid,
    )


def gap_side_receipt(*, declared_side: Any, source_side: Any) -> dict[str, Any]:
    valid = declared_side in {"buy", "sell"} and declared_side == source_side
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_SIDE_CONSISTENT" if valid else "GAP_SIDE_CONTRADICTION",
        fail_closed=not valid,
    )


def gap_overlap_receipt(*, existing_ids: Sequence[Any], backfill_ids: Sequence[Any], overlap_analyzed: bool) -> dict[str, Any]:
    overlap = set(existing_ids) & set(backfill_ids)
    valid = not overlap or overlap_analyzed is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_BACKFILL_OVERLAP_BOUND" if valid else "GAP_BACKFILL_OVERLAP_UNANALYZED",
        overlap_count=len(overlap),
        fail_closed=not valid,
    )


def gap_position_receipt(*, position_delta: Any, fill_deltas: Sequence[Any], tolerance: Any = _TOL) -> dict[str, Any]:
    valid = _finite(position_delta) and _finite(tolerance) and float(tolerance) >= 0 and isinstance(fill_deltas, Sequence) and all(_finite(value) for value in fill_deltas)
    if valid:
        error = float(position_delta) - sum(float(value) for value in fill_deltas)
        valid = abs(error) <= float(tolerance)
    else:
        error = None
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_POSITION_MATCHES_FILLS" if valid else "GAP_POSITION_FILL_MISMATCH",
        error=error,
        fail_closed=not valid,
    )


def gap_heartbeat_receipt(*, previous_ts_ms: Any, current_ts_ms: Any, max_gap_ms: Any) -> dict[str, Any]:
    valid = all(_integer(value) for value in (previous_ts_ms, current_ts_ms, max_gap_ms)) and 0 <= current_ts_ms - previous_ts_ms <= max_gap_ms
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_HEARTBEAT_CONTINUOUS" if valid else "GAP_HEARTBEAT_GAP",
        fail_closed=not valid,
    )


def gap_causality_receipt(*, event_ts_ms: Any, position_ts_ms: Any, observed_before_position: bool) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(position_ts_ms) and event_ts_ms <= position_ts_ms and observed_before_position is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_CAUSAL_OBSERVATION" if valid else "GAP_LOOKAHEAD_OR_UNOBSERVED",
        fail_closed=not valid,
    )


def gap_delta_receipt(*, before: Any, after: Any, fills: Sequence[Any], tolerance: Any = _TOL) -> dict[str, Any]:
    result = detecter(before, fills, after)
    valid = result.get("gap") is False and _finite(tolerance) and float(tolerance) >= 0
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="GAP_DELTA_EXPLAINED" if valid else "GAP_DELTA_UNEXPLAINED",
        detector=result,
        fail_closed=not valid,
    )


__all__ = [
    "detecter", "gap_contract_receipt", "gap_required_field_receipt", "gap_finite_receipt",
    "gap_cutoff_receipt", "gap_age_receipt", "gap_duplicate_receipt", "gap_retry_receipt",
    "gap_replay_receipt", "gap_rest_ws_receipt", "gap_timestamp_identity_receipt",
    "gap_tid_receipt", "gap_hash_receipt", "gap_close_open_receipt", "gap_wallet_receipt",
    "gap_side_receipt", "gap_overlap_receipt", "gap_position_receipt", "gap_heartbeat_receipt",
    "gap_causality_receipt", "gap_delta_receipt",
]
