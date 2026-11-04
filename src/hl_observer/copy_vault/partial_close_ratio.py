"""[COPY-VAULT pépite 290] PARTIAL-CLOSE RATIO : quand le leader réduit partiellement, on réplique en paper le
POURCENTAGE d'exposition réellement retiré, pas la quantité absolue du leader. Le leader et nous n'avons pas la
même taille de position ; copier « il a vendu 3 BTC » n'a aucun sens, « il a retiré 30% » en a un. On applique
ce ratio à NOTRE position. position_avant ≤ 0 → UNMEASURABLE (rien à réduire). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ratio_fermeture(qte_reduite: Any, position_avant: Any, *,
                    notre_position: Any = None) -> dict[str, Any]:
    """pct = qte_reduite / position_avant (borné à [0,1]). Si notre_position est fournie, on rend aussi la
    réduction paper à appliquer = pct × notre_position. position_avant ≤ 0 ou entrées invalides →
    UNMEASURABLE."""
    if not (_fini(qte_reduite) and _fini(position_avant)) or position_avant <= 0 or qte_reduite < 0:
        return {"pct": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    pct = min(1.0, float(qte_reduite) / float(position_avant))
    res: dict[str, Any] = {"pct": round(pct, 6)}
    if _fini(notre_position) and notre_position >= 0:
        res["notre_reduction"] = round(pct * float(notre_position), 8)
    return res


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _entier(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def ratio_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and _fini(row.get("reduced_quantity"))
        and _fini(row.get("leader_position_before"))
        and row.get("leader_position_before") > 0
        and row.get("reduced_quantity") >= 0
        and _entier(row.get("event_ts_ms"))
        and _entier(row.get("receive_ts_ms"))
        and row.get("receive_ts_ms") >= row.get("event_ts_ms")
        and bool(str(row.get("wallet") or "").strip())
    )
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="RATIO_CONTRACT_COMPLETE" if valid else "RATIO_CONTRACT_INCOMPLETE", fail_closed=not valid)


def ratio_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_FIELD_PRESENT" if valid else "RATIO_FIELD_MISSING", field=field, fail_closed=not valid)


def ratio_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_FIELD_TYPE_VALID" if valid else "RATIO_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def ratio_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_VALUE_FINITE" if valid else "RATIO_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def ratio_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_EVENT_WITHIN_CUTOFF" if valid else "RATIO_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def ratio_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_EVENT_AGE_VALID" if valid else "RATIO_EVENT_TOO_OLD", fail_closed=not valid)


def ratio_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_EVENTS_UNIQUE" if valid else "RATIO_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def ratio_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_RETRY_BOUNDED" if valid else "RATIO_RETRY_UNSAFE", fail_closed=not valid)


def ratio_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_REPLAY_DETERMINISTIC" if valid else "RATIO_REPLAY_DIVERGED", fail_closed=not valid)


def ratio_open_long_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(target_position) and current_position == 0 and target_position > 0
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_OPEN_LONG_FROM_FLAT" if valid else "RATIO_OPEN_LONG_INVALID", fail_closed=not valid)


def ratio_open_short_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(target_position) and current_position == 0 and target_position < 0
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_OPEN_SHORT_FROM_FLAT" if valid else "RATIO_OPEN_SHORT_INVALID", fail_closed=not valid)


def ratio_add_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "ADD" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_ADD_HAS_POSITION" if valid else "RATIO_ADD_WITHOUT_POSITION", fail_closed=not valid)


def ratio_reduce_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "REDUCE" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_REDUCE_HAS_POSITION" if valid else "RATIO_REDUCE_WITHOUT_POSITION", fail_closed=not valid)


def ratio_close_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "CLOSE" or (_fini(current_position) and current_position != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_CLOSE_HAS_POSITION" if valid else "RATIO_CLOSE_WITHOUT_POSITION", fail_closed=not valid)


def ratio_flip_receipt(*, from_position: Any, to_position: Any, intermediate_close: bool) -> dict[str, Any]:
    valid = _fini(from_position) and _fini(to_position) and from_position != 0 and to_position != 0 and from_position * to_position < 0 and intermediate_close is True
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_FLIP_HAS_INTERMEDIATE_CLOSE" if valid else "RATIO_FLIP_WITHOUT_INTERMEDIATE_CLOSE", fail_closed=not valid)


def ratio_reduce_only_receipt(*, current_position: Any, target_position: Any, reduce_only: bool) -> dict[str, Any]:
    if not (_fini(current_position) and _fini(target_position)) or reduce_only is not True:
        valid = False
    else:
        valid = abs(target_position) <= abs(current_position) and (target_position == 0 or current_position == 0 or current_position * target_position > 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_REDUCE_ONLY_NON_INCREASING" if valid else "RATIO_REDUCE_ONLY_INCREASE", fail_closed=not valid)


def ratio_close_remaining_receipt(*, current_position: Any, close_size: Any) -> dict[str, Any]:
    valid = _fini(current_position) and _fini(close_size) and close_size > 0 and close_size <= abs(current_position)
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_CLOSE_WITHIN_REMAINING" if valid else "RATIO_CLOSE_EXCEEDS_REMAINING", fail_closed=not valid)


def ratio_leverage_receipt(*, leverage: Any) -> dict[str, Any]:
    valid = _fini(leverage) and leverage > 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="RATIO_LEVERAGE_KNOWN" if valid else "RATIO_LEVERAGE_UNKNOWN", fail_closed=not valid)


def ratio_concurrent_add_close_receipt(*, actions: Sequence[Any], ordered: bool) -> dict[str, Any]:
    actions_list = list(actions) if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) else []
    has_both = "ADD" in actions_list and "CLOSE" in actions_list
    valid = not has_both or (ordered is True and len(actions_list) == len(set(actions_list)))
    return _base("PROVEN" if valid else "REJECTED", verdict="RATIO_ADD_CLOSE_ORDERED" if valid else "RATIO_ADD_CLOSE_CONCURRENT_UNSAFE", fail_closed=not valid)


def ratio_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close partial-close review only when every local check is proven."""

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
        verdict="RATIO_DONE_COVERED" if valid else "RATIO_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


__all__ = [
    "ratio_fermeture", "UNMEASURABLE", "ratio_contract_receipt", "ratio_required_field_receipt",
    "ratio_field_type_receipt", "ratio_finite_receipt", "ratio_cutoff_receipt", "ratio_age_receipt",
    "ratio_duplicate_receipt", "ratio_retry_receipt", "ratio_replay_receipt", "ratio_open_long_receipt",
    "ratio_open_short_receipt", "ratio_add_without_position_receipt", "ratio_reduce_without_position_receipt",
    "ratio_close_without_position_receipt", "ratio_flip_receipt", "ratio_reduce_only_receipt",
    "ratio_close_remaining_receipt", "ratio_leverage_receipt", "ratio_concurrent_add_close_receipt", "ratio_done_receipt",
]
