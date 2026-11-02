from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Iterable
from hl_observer.data_sources.market_backfill import HistoricalDataType, HistoricalRecord
class ReplayQuality(StrEnum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    UNMEASURABLE = "UNMEASURABLE"


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    accepted: bool
    reasons: tuple[str, ...] = ()


def validate_historical_record(record: HistoricalRecord) -> QualityVerdict:
    """Reject malformed rows before they can affect replay quality or ordering.

    Replay quality is a promotion gate, not a best-effort summary.  A row with
    an invalid exchange/receive timestamp or a malformed numeric field must
    therefore make the containing window unmeasurable instead of being silently
    ignored by downstream statistics.
    """

    reasons: list[str] = []
    if type(record.exchange_timestamp) is not int or record.exchange_timestamp <= 0:
        reasons.append("MISSING_TIMESTAMP")
    if record.receive_timestamp is not None and (
        type(record.receive_timestamp) is not int or record.receive_timestamp <= 0
    ):
        reasons.append("INVALID_RECEIVE_TIMESTAMP")
    for key in ("bid", "ask", "price", "size"):
        if key not in record.payload:
            continue
        if isinstance(record.payload[key], bool):
            reasons.append("INVALID_VALUE")
            continue
        try:
            value = float(record.payload[key])
        except (TypeError, ValueError, OverflowError):
            reasons.append("INVALID_VALUE")
            continue
        if not math.isfinite(value):
            reasons.append("NON_FINITE_VALUE")
        elif value < 0:
            reasons.append("NEGATIVE_VALUE")
    return QualityVerdict(not reasons, tuple(dict.fromkeys(reasons)))


def _all_records_valid(rows: Iterable[HistoricalRecord]) -> bool:
    return all(validate_historical_record(row).accepted for row in rows)


def determine_replay_quality(records:Iterable[HistoricalRecord])->ReplayQuality:
    rows=list(records); types={r.data_type for r in rows}
    if not rows or not _all_records_valid(rows):
        return ReplayQuality.UNMEASURABLE
    if {HistoricalDataType.TRADES,HistoricalDataType.BBO,HistoricalDataType.ORDER_BOOK_L2,HistoricalDataType.FUNDING,HistoricalDataType.OPEN_INTEREST,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE,HistoricalDataType.LIQUIDATIONS}<=types and all(type(r.sequence) is int for r in rows): return ReplayQuality.GOLD
    if {HistoricalDataType.TRADES,HistoricalDataType.BBO,HistoricalDataType.FUNDING,HistoricalDataType.OPEN_INTEREST}<=types:return ReplayQuality.SILVER
    if HistoricalDataType.OHLCV in types and HistoricalDataType.FUNDING in types:return ReplayQuality.BRONZE
    return ReplayQuality.UNMEASURABLE
def order_point_in_time(records:Iterable[HistoricalRecord],*,decision_timestamp:int)->list[HistoricalRecord]:
    seen=set(); out=[]
    for row in sorted((row for row in records if validate_historical_record(row).accepted),key=lambda r:(r.known_at,r.exchange_timestamp)):
        key=(row.venue,row.exchange_symbol,row.data_type,row.exchange_timestamp,row.event_id,row.payload.get("price"))
        if row.known_at<=decision_timestamp and key not in seen: seen.add(key); out.append(row)
    return out
__all__=["QualityVerdict","ReplayQuality","determine_replay_quality","order_point_in_time","validate_historical_record"]
