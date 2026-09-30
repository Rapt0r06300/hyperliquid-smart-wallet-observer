"""Live-versus-reference reconciliation for replay-quality collection windows."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    status: str
    live_count: int
    reference_count: int
    matched_count: int
    missing_from_live: int
    live_only: int
    duplicate_live_keys: int

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

    if not missing and not live_only and duplicates == 0:
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
    )


def _duplicate_count(rows: list[Mapping[str, Any]]) -> int:
    keys = [_key(row) for row in rows]
    present = [key for key in keys if key is not None]
    return max(0, len(present) - len(set(present)))


def _key(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    event_id = row.get("event_id", row.get("id"))
    if event_id not in {None, ""}:
        return ("event", str(event_id))
    sequence = row.get("sequence", row.get("seq", row.get("seqId")))
    ts = row.get(
        "exchange_timestamp",
        row.get("exchange_ts_ms", row.get("timestamp", row.get("ts"))),
    )
    symbol = row.get("exchange_symbol", row.get("symbol", row.get("instrument")))
    if sequence is None and ts is None:
        return None
    return ("market", str(symbol or ""), _intish(ts), _intish(sequence))


def _intish(value: Any) -> Any:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return str(value)


__all__ = ["ReconciliationReport", "reconcile_records"]
