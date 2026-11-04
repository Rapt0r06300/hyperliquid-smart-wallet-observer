"""[COPY-VAULT #68] POST-FILL SOURCE CONFIRMATION : après avoir reconstruit un delta à partir d'un fill, VÉRIFIER
que le snapshot de position du leader APRÈS le fill confirme bien ce delta (position_avant + delta ≈ snapshot_après).
Si le snapshot contredit le delta reconstruit, on ne fait pas confiance au delta (fill manqué, ordre partiel non
vu). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

_TOL_DEFAUT = 1e-6


def confirmer(position_avant: Any, delta_reconstruit: Any, snapshot_apres: Any, *,
              tol: float = _TOL_DEFAUT) -> dict[str, Any]:
    """Confirme si avant + delta ≈ snapshot_après (à `tol` près). Toute donnée manquante → NON_CONFIRME
    (on ne suppose jamais que le delta est bon)."""
    values = (position_avant, delta_reconstruit, snapshot_apres, tol)
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) for x in values) or float(tol) < 0:
        return {"confirme": False, "raison": "DONNEE_MANQUANTE"}
    attendu = float(position_avant) + float(delta_reconstruit)
    ecart = abs(attendu - float(snapshot_apres))
    ok = ecart <= float(tol)
    return {"confirme": bool(ok), "attendu": round(attendu, 12), "snapshot": round(float(snapshot_apres), 12),
            "ecart": round(ecart, 12), "raison": ("OK" if ok else "SNAPSHOT_CONTREDIT_DELTA")}


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _fini(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _entier(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def post_fill_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and _fini(row.get("position_before")) and _fini(row.get("delta")) and _fini(row.get("snapshot_after")) and _entier(row.get("event_ts_ms")) and _entier(row.get("receive_ts_ms")) and row.get("receive_ts_ms") >= row.get("event_ts_ms") and bool(str(row.get("wallet") or "").strip())
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="POST_FILL_CONTRACT_COMPLETE" if valid else "POST_FILL_CONTRACT_INCOMPLETE", fail_closed=not valid)


def post_fill_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_FIELD_PRESENT" if valid else "POST_FILL_FIELD_MISSING", field=field, fail_closed=not valid)


def post_fill_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_FIELD_TYPE_VALID" if valid else "POST_FILL_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def post_fill_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_VALUE_FINITE" if valid else "POST_FILL_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def post_fill_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_EVENT_WITHIN_CUTOFF" if valid else "POST_FILL_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def post_fill_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_EVENT_AGE_VALID" if valid else "POST_FILL_EVENT_TOO_OLD", fail_closed=not valid)


def post_fill_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_EVENTS_UNIQUE" if valid else "POST_FILL_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def post_fill_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_RETRY_BOUNDED" if valid else "POST_FILL_RETRY_UNSAFE", fail_closed=not valid)


def post_fill_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_REPLAY_DETERMINISTIC" if valid else "POST_FILL_REPLAY_DIVERGED", fail_closed=not valid)


def post_fill_open_long_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(target_position) and current_position == 0 and target_position > 0
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_OPEN_LONG_FROM_FLAT" if valid else "POST_FILL_OPEN_LONG_INVALID", fail_closed=not valid)


def post_fill_open_short_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(target_position) and current_position == 0 and target_position < 0
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_OPEN_SHORT_FROM_FLAT" if valid else "POST_FILL_OPEN_SHORT_INVALID", fail_closed=not valid)


def post_fill_add_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "ADD" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_ADD_HAS_POSITION" if valid else "POST_FILL_ADD_WITHOUT_POSITION", fail_closed=not valid)


def post_fill_reduce_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "REDUCE" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_REDUCE_HAS_POSITION" if valid else "POST_FILL_REDUCE_WITHOUT_POSITION", fail_closed=not valid)


def post_fill_close_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "CLOSE" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_CLOSE_HAS_POSITION" if valid else "POST_FILL_CLOSE_WITHOUT_POSITION", fail_closed=not valid)


def post_fill_flip_receipt(*, from_position: Any, to_position: Any, intermediate_close: bool) -> dict[str, Any]:
    valid = _fini(from_position) and _fini(to_position) and from_position != 0 and to_position != 0 and from_position * to_position < 0 and intermediate_close is True
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_FLIP_HAS_INTERMEDIATE_CLOSE" if valid else "POST_FILL_FLIP_WITHOUT_INTERMEDIATE_CLOSE", fail_closed=not valid)


def post_fill_reduce_only_receipt(*, current_position: Any, target_position: Any, reduce_only: bool) -> dict[str, Any]:
    if not (_fini(current_position) and _fini(target_position)) or reduce_only is not True:
        valid = False
    else:
        valid = abs(target_position) <= abs(current_position) and (target_position == 0 or current_position == 0 or current_position * target_position > 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_REDUCE_ONLY_NON_INCREASING" if valid else "POST_FILL_REDUCE_ONLY_INCREASE", fail_closed=not valid)


def post_fill_close_remaining_receipt(*, current_position: Any, close_size: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(close_size) and close_size > 0 and close_size <= abs(current_position)
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_CLOSE_WITHIN_REMAINING" if valid else "POST_FILL_CLOSE_EXCEEDS_REMAINING", fail_closed=not valid)


def post_fill_leverage_receipt(*, leverage: Any) -> dict[str, Any]:
    valid = _fini(leverage) and leverage > 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="POST_FILL_LEVERAGE_KNOWN" if valid else "POST_FILL_LEVERAGE_UNKNOWN", fail_closed=not valid)


def post_fill_concurrent_add_close_receipt(*, actions: Sequence[Any], ordered: bool) -> dict[str, Any]:
    actions_list = list(actions) if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) else []
    has_both = "ADD" in actions_list and "CLOSE" in actions_list
    valid = not has_both or (ordered is True and len(actions_list) == len(set(actions_list)))
    return _base("PROVEN" if valid else "REJECTED", verdict="POST_FILL_ADD_CLOSE_ORDERED" if valid else "POST_FILL_ADD_CLOSE_CONCURRENT_UNSAFE", fail_closed=not valid)


def post_fill_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close post-fill review only when every local check is proven."""

    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only") is True
        and check.get("real_execution") is False
        and check.get("fail_closed") is False
        and bool(str(check.get("verdict") or "").strip())
        for check in checks
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="POST_FILL_DONE_COVERED" if valid else "POST_FILL_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


__all__ = [
    "confirmer", "post_fill_contract_receipt", "post_fill_required_field_receipt", "post_fill_field_type_receipt",
    "post_fill_finite_receipt", "post_fill_cutoff_receipt", "post_fill_age_receipt", "post_fill_duplicate_receipt",
    "post_fill_retry_receipt", "post_fill_replay_receipt", "post_fill_open_long_receipt", "post_fill_open_short_receipt",
    "post_fill_add_without_position_receipt", "post_fill_reduce_without_position_receipt",
    "post_fill_close_without_position_receipt", "post_fill_flip_receipt", "post_fill_reduce_only_receipt",
    "post_fill_close_remaining_receipt", "post_fill_leverage_receipt", "post_fill_concurrent_add_close_receipt", "post_fill_done_receipt",
]
