"""Bitget USDT futures public collector (read-only)."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any
import httpx
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE, MarketLevel, NativeMarketSnapshot, UNMEASURABLE, canonical_coin

REST_BASE_URL="https://api.bitget.com"; PUBLIC_WS_URL="wss://ws.bitget.com/v2/ws/public"
def _f(v):
    try:return float(v)
    except (TypeError,ValueError):return None
def _i(v):
    try:return int(v)
    except (TypeError,ValueError):return None
def parse_bitget_instruments(payload: dict[str,Any]) -> list[tuple[str,str]]:
    out=[]
    for x in payload.get("data",[]) if isinstance(payload,dict) else []:
        if not isinstance(x,dict) or str(x.get("quoteCoin","")).upper()!="USDT" or str(x.get("symbolStatus", "normal")).lower() not in {"normal","listed"}: continue
        s=str(x.get("symbol") or "").upper(); b=str(x.get("baseCoin") or canonical_coin(s)).upper()
        if s and b: out.append((b,s))
    return sorted(set(out))
@dataclass(slots=True)
class BitgetMarketState:
    symbol:str; stale_after_ms:int=1000; bids:dict[float,float]=field(default_factory=dict); asks:dict[float,float]=field(default_factory=dict); sequence:int|None=None; exchange_ts_ms:int=0; receive_ts_ms:int=0; quality:str=UNMEASURABLE; reason:str="NO_SNAPSHOT"; last:float|None=None; mark:float|None=None; index:float|None=None; volume_24h:float|None=None; open_interest:float|None=None; funding_rate:float|None=None
    def apply(self,payload:dict[str,Any],*,receive_ts_ms:int|None=None)->str:
        arg=payload.get("arg") or {}; data=payload.get("data") or []; item=data[0] if data and isinstance(data[0],dict) else {}
        if str(arg.get("instId") or self.symbol).upper()!=self.symbol.upper(): self.quality,self.reason=DESYNC,"SYMBOL_MISMATCH"; return self.quality
        if str(arg.get("channel","")).lower() in {"books","books1"}:
            seq=_i(item.get("seq") or item.get("u"));
            if self.sequence is not None and seq is not None and seq<self.sequence: self.quality,self.reason=DESYNC,"SEQUENCE_REGRESSION"; return self.quality
            for raw,target in ((item.get("bids"),self.bids),(item.get("asks"),self.asks)):
                for row in raw or []:
                    if not isinstance(row,(list,tuple)) or len(row)<2: continue
                    p,s=_f(row[0]),_f(row[1]);
                    if p and s is not None: target[p]=s
            self.sequence=seq if seq is not None else self.sequence; self.quality=EXPLOITABLE if self.bids and self.asks and max(self.bids)<=min(self.asks) else UNMEASURABLE; self.reason="" if self.quality==EXPLOITABLE else "INVALID_BBO"
        self.exchange_ts_ms=_i(item.get("ts")) or self.exchange_ts_ms; self.receive_ts_ms=receive_ts_ms or int(time.time()*1000)
        self.last=_f(item.get("lastPr") or item.get("lastPrice")) or self.last; self.mark=_f(item.get("markPrice")) or self.mark; self.index=_f(item.get("indexPrice")) or self.index; self.funding_rate=_f(item.get("fundingRate")) if item.get("fundingRate") is not None else self.funding_rate; self.open_interest=_f(item.get("holdingAmount")) or self.open_interest
        return self.quality
    def snapshot(self,*,now_ms:int|None=None)->NativeMarketSnapshot:
        bids=tuple(MarketLevel(p,s) for p,s in sorted(self.bids.items(),reverse=True)); asks=tuple(MarketLevel(p,s) for p,s in sorted(self.asks.items())); return NativeMarketSnapshot.build(venue="bitget",coin=canonical_coin(self.symbol),exchange_symbol=self.symbol,bid=bids[0].price if bids else 0,ask=asks[0].price if asks else 0,bids=bids,asks=asks,exchange_ts_ms=self.exchange_ts_ms,receive_ts_ms=self.receive_ts_ms,now_ms=now_ms,stale_after_ms=self.stale_after_ms,quality=self.quality if self.quality in {DESYNC,UNMEASURABLE} else None,last=self.last,mark=self.mark,index=self.index,open_interest=self.open_interest,funding_rate=self.funding_rate,sequence=self.sequence,reason=self.reason)
class BitgetPublicClient:
    def __init__(self,*,rest_base_url=REST_BASE_URL,ws_url=PUBLIC_WS_URL): self.rest_base_url,self.ws_url=rest_base_url.rstrip("/"),ws_url
    def discover_usdt_perpetuals(self,*,timeout_s=10.0):
        with httpx.Client(timeout=timeout_s) as c: r=c.get(f"{self.rest_base_url}/api/v2/mix/market/contracts",params={"productType":"USDT-FUTURES"}); r.raise_for_status(); return parse_bitget_instruments(r.json())
    async def messages(self, symbols):
        import asyncio, json, websockets
        args=[{"instType":"USDT-FUTURES","channel":channel,"instId":symbol} for symbol in symbols for channel in ("books","ticker","trade")]
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
            await socket.send(json.dumps({"op":"subscribe","args":args}))
            async for raw in socket: yield json.loads(raw)
__all__=["BitgetMarketState","BitgetPublicClient","parse_bitget_instruments","REST_BASE_URL","PUBLIC_WS_URL"]
