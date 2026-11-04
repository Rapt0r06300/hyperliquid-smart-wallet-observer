"""[COPY-VAULT #78] TARGET-EXPOSURE RECONCILIATION : comparer RÉGULIÈREMENT l'exposition DÉSIRÉE (déduite des fills
du leader) à l'exposition paper réellement obtenue. Un écart persistant signale une réplication qui dérive
(fills manqués, arrondis, caps). On calcule l'ajustement à appliquer pour recoller à la cible. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


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


def reconcilier(exposition_cible: Any, exposition_paper: Any, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Écart = cible − paper. |écart| ≤ tolérance → aligné. Sinon → ajustement à appliquer (delta signé).
    Donnée manquante → UNMEASURABLE (on ne devine pas l'écart)."""
    if not all(_finite(x) for x in (exposition_cible, exposition_paper)) or not _finite(tolerance) or float(tolerance) < 0:
        return {"aligne": False, "ajustement": UNMEASURABLE, "raison": "EXPOSITION_MANQUANTE"}
    ecart = float(exposition_cible) - float(exposition_paper)
    if abs(ecart) <= float(tolerance):
        return {"aligne": True, "ajustement": 0.0, "raison": "ALIGNE"}
    return {"aligne": False, "ajustement": round(ecart, 12),
            "sens": ("ACHAT" if ecart > 0 else "VENTE"), "raison": "DERIVE_A_CORRIGER"}


def exposure_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and _finite(row.get("target_exposure"))
        and _finite(row.get("paper_exposure"))
        and _integer(row.get("event_ts_ms"))
        and _integer(row.get("receive_ts_ms"))
        and row.get("receive_ts_ms") >= row.get("event_ts_ms")
        and bool(str(row.get("wallet") or "").strip())
    )
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="EXPOSURE_CONTRACT_COMPLETE" if valid else "EXPOSURE_CONTRACT_INCOMPLETE", fail_closed=not valid)


def exposure_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_FIELD_PRESENT" if valid else "EXPOSURE_FIELD_MISSING", field=field, fail_closed=not valid)


def exposure_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_FIELD_TYPE_VALID" if valid else "EXPOSURE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def exposure_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _finite(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_VALUE_FINITE" if valid else "EXPOSURE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def exposure_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_EVENT_WITHIN_CUTOFF" if valid else "EXPOSURE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def exposure_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_EVENT_AGE_VALID" if valid else "EXPOSURE_EVENT_TOO_OLD", fail_closed=not valid)


def exposure_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_EVENTS_UNIQUE" if valid else "EXPOSURE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def exposure_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _integer(attempts) and _integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_RETRY_BOUNDED" if valid else "EXPOSURE_RETRY_UNSAFE", fail_closed=not valid)


def exposure_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="EXPOSURE_REPLAY_DETERMINISTIC" if valid else "EXPOSURE_REPLAY_DIVERGED", fail_closed=not valid)


def exposure_open_long_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(target_position) and float(current_position) == 0 and float(target_position) > 0
    return _base("PROVEN" if valid else "REJECTED", verdict="OPEN_LONG_FROM_FLAT" if valid else "OPEN_LONG_INVALID", fail_closed=not valid)


def exposure_open_short_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(target_position) and float(current_position) == 0 and float(target_position) < 0
    return _base("PROVEN" if valid else "REJECTED", verdict="OPEN_SHORT_FROM_FLAT" if valid else "OPEN_SHORT_INVALID", fail_closed=not valid)


def exposure_add_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "ADD" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="ADD_HAS_POSITION" if valid else "ADD_WITHOUT_POSITION", fail_closed=not valid)


def exposure_reduce_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "REDUCE" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="REDUCE_HAS_POSITION" if valid else "REDUCE_WITHOUT_POSITION", fail_closed=not valid)


def exposure_close_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "CLOSE" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="CLOSE_HAS_POSITION" if valid else "CLOSE_WITHOUT_POSITION", fail_closed=not valid)


def exposure_flip_receipt(*, from_position: Any, to_position: Any, intermediate_close: bool) -> dict[str, Any]:
    valid = _finite(from_position) and _finite(to_position) and float(from_position) != 0 and float(to_position) != 0 and float(from_position) * float(to_position) < 0 and intermediate_close is True
    return _base("PROVEN" if valid else "REJECTED", verdict="FLIP_HAS_INTERMEDIATE_CLOSE" if valid else "FLIP_WITHOUT_INTERMEDIATE_CLOSE", fail_closed=not valid)


def exposure_reduce_only_receipt(*, current_position: Any, target_position: Any, reduce_only: bool) -> dict[str, Any]:
    if not (_finite(current_position) and _finite(target_position)) or reduce_only is not True:
        valid = False
    else:
        current = float(current_position); target = float(target_position)
        valid = abs(target) <= abs(current) and (target == 0 or current == 0 or current * target > 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="REDUCE_ONLY_NON_INCREASING" if valid else "REDUCE_ONLY_INCREASE", fail_closed=not valid)


def exposure_close_remaining_receipt(*, current_position: Any, close_size: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(close_size) and float(close_size) > 0 and float(close_size) <= abs(float(current_position))
    return _base("PROVEN" if valid else "REJECTED", verdict="CLOSE_WITHIN_REMAINING" if valid else "CLOSE_EXCEEDS_REMAINING", fail_closed=not valid)


def exposure_leverage_receipt(*, leverage: Any) -> dict[str, Any]:
    valid = _finite(leverage) and float(leverage) > 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="LEVERAGE_KNOWN" if valid else "LEVERAGE_UNKNOWN", fail_closed=not valid)


def exposure_concurrent_add_close_receipt(*, actions: Sequence[Any], ordered: bool) -> dict[str, Any]:
    actions_list = list(actions) if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) else []
    has_both = "ADD" in actions_list and "CLOSE" in actions_list
    valid = not has_both or (ordered is True and len(actions_list) == len(set(actions_list)))
    return _base("PROVEN" if valid else "REJECTED", verdict="ADD_CLOSE_ORDERED" if valid else "ADD_CLOSE_CONCURRENT_UNSAFE", fail_closed=not valid)


__all__ = [
    "reconcilier", "UNMEASURABLE", "exposure_contract_receipt", "exposure_required_field_receipt",
    "exposure_field_type_receipt", "exposure_finite_receipt", "exposure_cutoff_receipt",
    "exposure_age_receipt", "exposure_duplicate_receipt", "exposure_retry_receipt",
    "exposure_replay_receipt", "exposure_open_long_receipt", "exposure_open_short_receipt",
    "exposure_add_without_position_receipt", "exposure_reduce_without_position_receipt",
    "exposure_close_without_position_receipt", "exposure_flip_receipt", "exposure_reduce_only_receipt",
    "exposure_close_remaining_receipt", "exposure_leverage_receipt", "exposure_concurrent_add_close_receipt",
]
