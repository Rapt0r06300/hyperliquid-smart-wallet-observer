"""Live-versus-reference reconciliation for replay-quality collection windows."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_KNOWN_VENUES = (
    "hyperliquid",
    "binance",
    "bybit",
    "okx",
    "bitget",
    "gate",
    "deribit",
    "kraken",
    "coinbase",
    "htx",
)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    status: str
    live_count: int
    reference_count: int
    matched_count: int
    missing_from_live: int
    live_only: int
    duplicate_live_keys: int
    value_conflicts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_records(
    live_records: Iterable[Mapping[str, Any]],
    reference_records: Iterable[Mapping[str, Any]],
) -> ReconciliationReport:
    live = list(live_records)
    reference = list(reference_records)
    if not reference:
        return ReconciliationReport(
            "UNAVAILABLE", len(live), 0, 0, 0, len(live), _duplicate_count(live)
        )

    live_keys = [_key(row) for row in live]
    ref_keys = [_key(row) for row in reference]
    live_set = {key for key in live_keys if key is not None}
    ref_set = {key for key in ref_keys if key is not None}
    matched = live_set & ref_set
    missing = ref_set - live_set
    live_only = live_set - ref_set
    duplicates = len([key for key in live_keys if key is not None]) - len(live_set)
    value_conflicts = _value_conflicts(live, reference, matched)
    unidentified = sum(key is None for key in live_keys) + sum(key is None for key in ref_keys)

    if value_conflicts or unidentified:
        status = "MISMATCH"
    elif not missing and not live_only and duplicates == 0:
        status = "MATCHED"
    elif matched:
        status = "PARTIAL"
    else:
        status = "MISMATCH"
    return ReconciliationReport(
        status=status,
        live_count=len(live),
        reference_count=len(reference),
        matched_count=len(matched),
        missing_from_live=len(missing),
        live_only=len(live_only),
        duplicate_live_keys=max(0, duplicates),
        value_conflicts=value_conflicts,
    )


def merge_reconciled_records(
    live_records: Iterable[Mapping[str, Any]],
    reference_records: Iterable[Mapping[str, Any]],
) -> tuple[tuple[dict[str, Any], ...], ReconciliationReport]:
    """Fill identity-proven archive gaps without replacing richer live evidence.

    Live records always win on overlap because only they can carry real receive-time
    evidence. Archive-only records retain explicit provenance and are appended in
    reference order. Conflicting values remain visible through the fail-closed report.
    """

    live = list(live_records)
    reference = list(reference_records)
    report = reconcile_records(live, reference)
    live_keys = {_key(row) for row in live}
    merged = [dict(row) for row in live]
    for row in reference:
        key = _key(row)
        if key is not None and key in live_keys:
            continue
        archive_row = dict(row)
        archive_row.setdefault("provenance", "official_archive")
        merged.append(archive_row)
        if key is not None:
            live_keys.add(key)
    return tuple(merged), report


def _duplicate_count(rows: list[Mapping[str, Any]]) -> int:
    keys = [_key(row) for row in rows]
    present = [key for key in keys if key is not None]
    return max(0, len(present) - len(set(present)))


def _key(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    payload = _raw_mapping(row)
    venue = _canonical_venue(_first(row, payload, "venue", "source_id"))
    symbol = str(_first(row, payload, "exchange_symbol", "symbol", "instrument") or "").upper()
    event_id = _first(
        row,
        payload,
        "trade_id",
        "tradeId",
        "event_id",
        "id",
    )
    if event_id in {None, ""} and venue == "binance":
        event_id = _first(row, payload, "t", "a")
    if event_id in {None, ""} and venue == "bybit":
        event_id = _first(row, payload, "i")
    if event_id not in {None, ""}:
        return ("event", venue, symbol, str(event_id))
    sequence = _first(row, payload, "sequence", "seq", "seqId", "seqNum", "u")
    channel = str(_first(row, payload, "channel", "event_kind", "topic") or "").lower()
    if sequence is not None:
        return ("sequence", venue, symbol, channel, _intish(sequence))
    raw = row.get("raw_payload")
    if raw is None:
        return None
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    return ("raw", venue, symbol, hashlib.sha256(encoded).hexdigest())


def _value_conflicts(
    live: list[Mapping[str, Any]],
    reference: list[Mapping[str, Any]],
    matched: set[tuple[Any, ...]],
) -> int:
    live_by_key = {_key(row): row for row in live if _key(row) is not None}
    ref_by_key = {_key(row): row for row in reference if _key(row) is not None}
    conflicts = 0
    for key in matched:
        left = _comparable_values(live_by_key[key])
        right = _comparable_values(ref_by_key[key])
        shared = left.keys() & right.keys()
        if any(left[field] != right[field] for field in shared):
            conflicts += 1
    return conflicts


def _comparable_values(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = _raw_mapping(row)
    values = {
        "timestamp": _first(
            row,
            payload,
            "exchange_timestamp",
            "exchange_ts_ms",
            "timestamp",
            "time",
            "ts",
            "T",
        ),
        "price": _first(row, payload, "price", "p", "px"),
        "quantity": _first(row, payload, "quantity", "qty", "size", "q", "v"),
    }
    return {
        name: _decimalish(value)
        for name, value in values.items()
        if value is not None and value != ""
    }


def _raw_mapping(row: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = row.get("raw_payload")
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    return {}


def _first(row: Mapping[str, Any], payload: Mapping[str, Any], *names: str) -> Any:
    for source in (row, payload):
        for name in names:
            value = source.get(name)
            if value is not None and value != "":
                return value
    return None


def _canonical_venue(value: Any) -> str:
    venue = str(value or "").lower()
    for known in _KNOWN_VENUES:
        if known in venue:
            return known
    return venue


def _decimalish(value: Any) -> Any:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _intish(value: Any) -> Any:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return str(value)


__all__ = ["ReconciliationReport", "merge_reconciled_records", "reconcile_records"]
