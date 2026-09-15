from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable
from hl_observer.data_sources.market_backfill import HistoricalDataType, HistoricalRecord
class ReplayQuality(StrEnum): BRONZE="BRONZE"; SILVER="SILVER"; GOLD="GOLD"; UNMEASURABLE="UNMEASURABLE"
@dataclass(frozen=True, slots=True)
class QualityVerdict: accepted:bool; reasons:tuple[str,...]=()
def determine_replay_quality(records:Iterable[HistoricalRecord])->ReplayQuality:
    rows=list(records); types={r.data_type for r in rows}
    if not rows:return ReplayQuality.UNMEASURABLE
    if {HistoricalDataType.TRADES,HistoricalDataType.BBO,HistoricalDataType.ORDER_BOOK_L2,HistoricalDataType.FUNDING,HistoricalDataType.OPEN_INTEREST,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE,HistoricalDataType.LIQUIDATIONS}<=types and all(r.sequence is not None and r.exchange_timestamp>0 for r in rows): return ReplayQuality.GOLD
    if {HistoricalDataType.TRADES,HistoricalDataType.BBO,HistoricalDataType.FUNDING,HistoricalDataType.OPEN_INTEREST}<=types:return ReplayQuality.SILVER
    if HistoricalDataType.OHLCV in types and HistoricalDataType.FUNDING in types:return ReplayQuality.BRONZE
    return ReplayQuality.UNMEASURABLE
def order_point_in_time(records:Iterable[HistoricalRecord],*,decision_timestamp:int)->list[HistoricalRecord]:
    seen=set(); out=[]
    for row in sorted(records,key=lambda r:(r.known_at,r.exchange_timestamp)):
        key=(row.venue,row.exchange_symbol,row.data_type,row.exchange_timestamp,row.event_id,row.payload.get("price"))
        if row.known_at<=decision_timestamp and key not in seen: seen.add(key); out.append(row)
    return out
def validate_historical_record(record:HistoricalRecord)->QualityVerdict:
    reasons=[]
    if record.exchange_timestamp<=0: reasons.append("MISSING_TIMESTAMP")
    for key in ("bid","ask","price","size"):
        if key in record.payload:
            try:
                if float(record.payload[key])<0: reasons.append("NEGATIVE_VALUE")
            except (TypeError,ValueError): reasons.append("INVALID_VALUE")
    return QualityVerdict(not reasons,tuple(reasons))
__all__=["QualityVerdict","ReplayQuality","determine_replay_quality","order_point_in_time","validate_historical_record"]
