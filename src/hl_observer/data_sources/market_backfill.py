"""Bounded, read-only historical market ingestion with local/Tardis support."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
import csv, json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

class HistoricalDataType(StrEnum):
    OHLCV="OHLCV"; TRADES="TRADES"; BBO="BBO"; ORDER_BOOK_L2="ORDER_BOOK_L2"; FUNDING="FUNDING"; OPEN_INTEREST="OPEN_INTEREST"; LIQUIDATIONS="LIQUIDATIONS"; MARK_PRICE="MARK_PRICE"; INDEX_PRICE="INDEX_PRICE"
@dataclass(frozen=True, slots=True)
class HistoricalRecord:
    venue:str; canonical_coin:str; exchange_symbol:str; data_type:HistoricalDataType; exchange_timestamp:int; receive_timestamp:int|None; source:str; provenance:str; normalized:bool=True; sequence:int|None=None; event_id:str|None=None; payload:Mapping[str,Any]=field(default_factory=dict)
    @property
    def known_at(self)->int:return self.receive_timestamp if self.receive_timestamp is not None else self.exchange_timestamp
@dataclass(frozen=True, slots=True)
class BackfillRequest:
    venue:str; canonical_coin:str; exchange_symbol:str; data_type:HistoricalDataType; start_timestamp:int; end_timestamp:int; limit:int=100_000; adapter:str|None=None
@dataclass(frozen=True, slots=True)
class BackfillResult:
    status:str; records:tuple[HistoricalRecord,...]=(); error:str|None=None

class LocalFileAdapter:
    name="local"; capabilities=frozenset(HistoricalDataType)
    def __init__(self,name,path,field_map=None): self.name=name; self.path=Path(path); self.field_map=field_map or {}
    def fetch(self,request):
        text=self.path.read_text(encoding="utf-8"); rows=list(csv.DictReader(text.splitlines())) if self.path.suffix.lower()==".csv" else ([json.loads(x) for x in text.splitlines() if x.strip()] if self.path.suffix.lower() in {".jsonl",".ndjson"} else json.loads(text))
        if isinstance(rows,dict): rows=rows.get("records",[])
        return tuple(_normalize(row,request,source=self.name,provenance=str(self.path)) for row in rows if isinstance(row,Mapping) and _in_range(row.get(self.field_map.get("timestamp","timestamp"),row.get("ts")),request))[:request.limit]

class TardisFileAdapter(LocalFileAdapter):
    name="tardis"
    def __init__(self,path): super().__init__("tardis",path,{"timestamp":"timestamp","receive_timestamp":"local_timestamp"})
    def fetch(self,request): return tuple(_normalize(row,request,source="TARDIS",provenance=str(self.path),tardis=True) for row in self._rows() if _in_range(row.get("timestamp"),request))[:request.limit]
    def _rows(self):
        text=self.path.read_text(encoding="utf-8"); return [json.loads(x) for x in text.splitlines() if x.strip()]

class OfficialAdapter:
    def __init__(self,name,capabilities,fetch_json): self.name=name; self.capabilities=frozenset(capabilities); self.fetch_json=fetch_json
    def fetch(self,request):
        if request.data_type not in self.capabilities: return ()
        return tuple(_normalize(row,request,source=self.name.upper(),provenance="official_public_api") for row in (self.fetch_json(self.name,request) or []) if isinstance(row,Mapping))[:request.limit]
def build_official_adapters(*,fetch_json:Callable[...,Iterable[Mapping[str,Any]]]):
    common={HistoricalDataType.OHLCV,HistoricalDataType.TRADES,HistoricalDataType.FUNDING,HistoricalDataType.OPEN_INTEREST}
    return {"binance":OfficialAdapter("binance",common|{HistoricalDataType.BBO,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE,HistoricalDataType.LIQUIDATIONS},fetch_json),"okx":OfficialAdapter("okx",common|{HistoricalDataType.BBO,HistoricalDataType.ORDER_BOOK_L2,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE},fetch_json),"bybit":OfficialAdapter("bybit",common|{HistoricalDataType.BBO,HistoricalDataType.LIQUIDATIONS},fetch_json),"gate":OfficialAdapter("gate",common|{HistoricalDataType.BBO,HistoricalDataType.ORDER_BOOK_L2,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE},fetch_json),"bitget":OfficialAdapter("bitget",common|{HistoricalDataType.BBO,HistoricalDataType.ORDER_BOOK_L2,HistoricalDataType.MARK_PRICE,HistoricalDataType.INDEX_PRICE},fetch_json)}
class HistoricalBackfillHub:
    def __init__(self,adapters:Iterable[Any]=()): self.adapters={a.name:a for a in adapters}
    def register(self,adapter): self.adapters[adapter.name]=adapter
    def backfill(self,request):
        adapter=self.adapters.get(request.adapter or request.venue)
        if adapter is None:return BackfillResult("UNAVAILABLE",error="NO_ADAPTER")
        try:return BackfillResult("OK",tuple(sorted(adapter.fetch(request),key=lambda r:(r.exchange_timestamp,r.known_at))))
        except Exception as exc:return BackfillResult("ERROR",error=f"{type(exc).__name__}: {exc}")
    def backfill_many(self,requests): return [self.backfill(r) for r in requests]
def _in_range(value,request):
    ts=_timestamp(value); return ts is not None and int(request.start_timestamp)<=ts<=int(request.end_timestamp)
def _timestamp(value):
    if isinstance(value,(int,float)): return int(value)
    if isinstance(value,str):
        try:return int(float(value))
        except ValueError:
            from datetime import datetime
            try:return int(datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()*1000)
            except ValueError:return None
    return None
def _normalize(row,request,source,provenance,tardis=False):
    ts=_timestamp(row.get("timestamp",row.get("ts",row.get("time")))) or 0; recv=_timestamp(row.get("local_timestamp",row.get("receive_timestamp"))) if tardis else None
    return HistoricalRecord(request.venue,request.canonical_coin.upper(),request.exchange_symbol,request.data_type,ts,recv,source,provenance,True,row.get("sequence",row.get("seq")),row.get("id"),dict(row))
__all__=["BackfillRequest","BackfillResult","HistoricalBackfillHub","HistoricalDataType","HistoricalRecord","LocalFileAdapter","OfficialAdapter","TardisFileAdapter","build_official_adapters"]
