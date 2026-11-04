"""[COPY-VAULT lot2 #41] LEADER-STATE VERSIONING : chaque snapshot (equity + positions) du leader reçoit un NUMÉRO
DE VERSION immuable et monotone. La version permet de savoir si deux lectures viennent du même instant logique et de
rendre les décisions reproductibles/traçables. Une fois émise, une version ne change plus. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
import math
from typing import Any


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


class VersionneurEtat:
    """Attribue une version monotone à chaque snapshot equity+positions. Les snapshots passés restent immuables."""

    def __init__(self) -> None:
        self._version = 0
        self._snapshots: dict[int, dict[str, Any]] = {}

    def nouveau_snapshot(self, *, equity: Any, positions: Any) -> dict[str, Any]:
        """Émet un nouveau snapshot versionné. Copie PROFONDE au stockage ET au retour : muter la valeur rendue
        n'affecte jamais le snapshot stocké (immutabilité réelle)."""
        self._version += 1
        snap = {"version": self._version, "equity": equity, "positions": copy.deepcopy(positions)}
        self._snapshots[self._version] = snap
        return copy.deepcopy(snap)

    def version_courante(self) -> int:
        return self._version

    def obtenir(self, version: int) -> Any:
        s = self._snapshots.get(int(version))
        return copy.deepcopy(s) if s is not None else None


def leader_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and _integer(row.get("version"))
        and row.get("version") > 0
        and _finite(row.get("equity"))
        and isinstance(row.get("positions"), Mapping)
        and bool(str(row.get("wallet") or "").strip())
        and _integer(row.get("event_ts_ms"))
        and _integer(row.get("receive_ts_ms"))
        and row.get("receive_ts_ms") >= row.get("event_ts_ms")
    )
    return _base(
        "PROVEN" if valid else "UNMEASURABLE",
        verdict="LEADER_STATE_CONTRACT_COMPLETE" if valid else "LEADER_STATE_CONTRACT_INCOMPLETE",
        fail_closed=not valid,
    )


def leader_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_FIELD_PRESENT" if valid else "LEADER_FIELD_MISSING", field=field, fail_closed=not valid)


def leader_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_FIELD_TYPE_VALID" if valid else "LEADER_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def leader_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _finite(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_VALUE_FINITE" if valid else "LEADER_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def leader_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_EVENT_WITHIN_CUTOFF" if valid else "LEADER_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def leader_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_EVENT_AGE_VALID" if valid else "LEADER_EVENT_TOO_OLD", fail_closed=not valid)


def leader_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_EVENTS_UNIQUE" if valid else "LEADER_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def leader_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _integer(attempts) and _integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_RETRY_BOUNDED" if valid else "LEADER_RETRY_UNSAFE", fail_closed=not valid)


def leader_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_REPLAY_DETERMINISTIC" if valid else "LEADER_REPLAY_DIVERGED", fail_closed=not valid)


def leader_rest_ws_receipt(*, ws_identity: Any, rest_identity: Any) -> dict[str, Any]:
    valid = bool(str(ws_identity or "").strip()) and ws_identity == rest_identity
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_REST_WS_MATCH" if valid else "LEADER_REST_WS_DIVERGENCE", fail_closed=not valid)


def leader_timestamp_identity_receipt(*, identities: Sequence[Any]) -> dict[str, Any]:
    valid = bool(identities) and all(str(value).strip() for value in identities) and len(identities) == len(set(identities))
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_TIMESTAMP_IDENTITIES_STABLE" if valid else "LEADER_TIMESTAMP_IDENTITY_COLLISION", fail_closed=not valid)


def leader_tid_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and row.get("tid") not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_TID_PRESENT" if valid else "LEADER_TID_MISSING", fail_closed=not valid)


def leader_hash_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("hash") if isinstance(row, Mapping) else None
    valid = isinstance(value, str) and len(value) >= 8 and all(character in "0123456789abcdefABCDEF" for character in value)
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_HASH_PRESENT" if valid else "LEADER_HASH_MISSING_OR_INVALID", fail_closed=not valid)


def leader_close_open_receipt(*, open_ids: Sequence[Any], close_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(close_ids) and all(value in set(open_ids) for value in close_ids)
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_CLOSE_HAS_OPEN" if valid else "LEADER_CLOSE_WITHOUT_OPEN", fail_closed=not valid)


def leader_wallet_receipt(*, expected_wallet: Any, observed_wallet: Any) -> dict[str, Any]:
    valid = bool(str(expected_wallet or "").strip()) and expected_wallet == observed_wallet
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_WALLET_MATCH" if valid else "LEADER_WALLET_MISMATCH", fail_closed=not valid)


def leader_side_receipt(*, declared_side: Any, source_side: Any) -> dict[str, Any]:
    valid = declared_side in {"buy", "sell"} and declared_side == source_side
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_SIDE_CONSISTENT" if valid else "LEADER_SIDE_CONTRADICTION", fail_closed=not valid)


def leader_overlap_receipt(*, existing_ids: Sequence[Any], backfill_ids: Sequence[Any], overlap_analyzed: bool) -> dict[str, Any]:
    overlap = set(existing_ids) & set(backfill_ids)
    valid = not overlap or overlap_analyzed is True
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_BACKFILL_OVERLAP_BOUND" if valid else "LEADER_BACKFILL_OVERLAP_UNANALYZED", overlap_count=len(overlap), fail_closed=not valid)


def leader_position_receipt(*, position_delta: Any, fill_deltas: Sequence[Any], tolerance: Any = 1e-9) -> dict[str, Any]:
    valid = _finite(position_delta) and _finite(tolerance) and float(tolerance) >= 0 and isinstance(fill_deltas, Sequence) and all(_finite(value) for value in fill_deltas)
    if valid:
        error = float(position_delta) - sum(float(value) for value in fill_deltas)
        valid = abs(error) <= float(tolerance)
    else:
        error = None
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_POSITION_MATCHES_FILLS" if valid else "LEADER_POSITION_FILL_MISMATCH", error=error, fail_closed=not valid)


def leader_heartbeat_receipt(*, previous_ts_ms: Any, current_ts_ms: Any, max_gap_ms: Any) -> dict[str, Any]:
    valid = all(_integer(value) for value in (previous_ts_ms, current_ts_ms, max_gap_ms)) and 0 <= current_ts_ms - previous_ts_ms <= max_gap_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_HEARTBEAT_CONTINUOUS" if valid else "LEADER_HEARTBEAT_GAP", fail_closed=not valid)


def leader_causality_receipt(*, event_ts_ms: Any, state_ts_ms: Any, observed_before_state: bool) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(state_ts_ms) and event_ts_ms <= state_ts_ms and observed_before_state is True
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_CAUSAL_OBSERVATION" if valid else "LEADER_LOOKAHEAD_OR_UNOBSERVED", fail_closed=not valid)


__all__ = [
    "VersionneurEtat", "leader_contract_receipt", "leader_required_field_receipt",
    "leader_field_type_receipt", "leader_finite_receipt", "leader_cutoff_receipt",
    "leader_age_receipt", "leader_duplicate_receipt", "leader_retry_receipt",
    "leader_replay_receipt", "leader_rest_ws_receipt", "leader_timestamp_identity_receipt",
    "leader_tid_receipt", "leader_hash_receipt", "leader_close_open_receipt",
    "leader_wallet_receipt", "leader_side_receipt", "leader_overlap_receipt",
    "leader_position_receipt", "leader_heartbeat_receipt", "leader_causality_receipt",
]
