"""Bitget USDT futures public collector (read-only)."""
from __future__ import annotations
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Mapping

import httpx
import websockets

from hl_observer.collection.backoff import compute_backoff_delay
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
    symbol:str; stale_after_ms:int=1000; bids:dict[float,float]=field(default_factory=dict); asks:dict[float,float]=field(default_factory=dict); sequence:int|None=None; exchange_ts_ms:int=0; receive_ts_ms:int=0; quality:str=UNMEASURABLE; reason:str="NO_SNAPSHOT"; last:float|None=None; mark:float|None=None; index:float|None=None; volume_24h:float|None=None; open_interest:float|None=None; funding_rate:float|None=None; receive_mono_ns:int|None=None; connection_id:str|None=None; transport_rtt_ms:float|None=None; clock_offset_ms:float|None=None; regression_count:int=0
    def apply(self,payload:dict[str,Any],*,receive_ts_ms:int|None=None)->str:
        arg=payload.get("arg") or {}; data=payload.get("data") or []; item=data[0] if data and isinstance(data[0],dict) else {}
        meta=payload.get("_alina_transport"); transport=dict(meta) if isinstance(meta,Mapping) else {}
        if str(arg.get("instId") or self.symbol).upper()!=self.symbol.upper(): self.quality,self.reason=DESYNC,"SYMBOL_MISMATCH"; return self.quality
        if str(arg.get("channel","")).lower() in {"books","books1"}:
            seq=_i(item.get("seq") or item.get("u"));
            if self.sequence is not None and seq is not None and seq<self.sequence:
                self.regression_count += 1
                self.quality,self.reason=DESYNC,"SEQUENCE_REGRESSION"; return self.quality
            for raw,target in ((item.get("bids"),self.bids),(item.get("asks"),self.asks)):
                for row in raw or []:
                    if not isinstance(row,(list,tuple)) or len(row)<2: continue
                    p,s=_f(row[0]),_f(row[1]);
                    if p and s is not None: target[p]=s
            self.sequence=seq if seq is not None else self.sequence; self.quality=EXPLOITABLE if self.bids and self.asks and max(self.bids)<=min(self.asks) else UNMEASURABLE; self.reason="" if self.quality==EXPLOITABLE else "INVALID_BBO"
        self.exchange_ts_ms=_i(item.get("ts")) or self.exchange_ts_ms; self.receive_ts_ms=receive_ts_ms or _i(transport.get("receive_wall_ts_ms")) or int(time.time()*1000)
        self.receive_mono_ns=_i(transport.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id=str(transport.get("connection_id") or "") or self.connection_id
        self.transport_rtt_ms=_f(transport.get("transport_rtt_ms")) if transport.get("transport_rtt_ms") is not None else self.transport_rtt_ms
        self.clock_offset_ms=_f(transport.get("clock_offset_ms")) if transport.get("clock_offset_ms") is not None else self.clock_offset_ms
        self.last=_f(item.get("lastPr") or item.get("lastPrice")) or self.last; self.mark=_f(item.get("markPrice")) or self.mark; self.index=_f(item.get("indexPrice")) or self.index; self.funding_rate=_f(item.get("fundingRate")) if item.get("fundingRate") is not None else self.funding_rate; self.open_interest=_f(item.get("holdingAmount")) or self.open_interest
        return self.quality
    def snapshot(self,*,now_ms:int|None=None)->NativeMarketSnapshot:
        bids=tuple(MarketLevel(p,s) for p,s in sorted(self.bids.items(),reverse=True)); asks=tuple(MarketLevel(p,s) for p,s in sorted(self.asks.items())); return NativeMarketSnapshot.build(venue="bitget",coin=canonical_coin(self.symbol),exchange_symbol=self.symbol,bid=bids[0].price if bids else 0,ask=asks[0].price if asks else 0,bids=bids,asks=asks,exchange_ts_ms=self.exchange_ts_ms,receive_ts_ms=self.receive_ts_ms,now_ms=now_ms,stale_after_ms=self.stale_after_ms,quality=self.quality if self.quality in {DESYNC,UNMEASURABLE} else None,last=self.last,mark=self.mark,index=self.index,open_interest=self.open_interest,funding_rate=self.funding_rate,sequence=self.sequence,connection_id=self.connection_id,receive_mono_ns=self.receive_mono_ns,transport_rtt_ms=self.transport_rtt_ms,clock_offset_ms=self.clock_offset_ms,regression_count=self.regression_count,reason=self.reason)
class BitgetPublicClient:
    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_url: str = PUBLIC_WS_URL,
        session_refresh_s: float = 900.0,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url
        self.session_refresh_s = max(60.0, float(session_refresh_s))
        self.last_instrument_metadata: list[dict[str, Any]] = []

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0):
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(
                f"{self.rest_base_url}/api/v2/mix/market/contracts",
                params={"productType": "USDT-FUTURES"},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        self.last_instrument_metadata = [dict(row) for row in (data or []) if isinstance(row, dict)]
        return parse_bitget_instruments(payload)

    async def messages(self, symbols: Iterable[str]) -> AsyncIterator[dict[str, Any]]:
        symbols = tuple(sorted({str(s).upper() for s in symbols if str(s).strip()}))
        if not symbols:
            return
        args = [
            {"instType": "USDT-FUTURES", "channel": channel, "instId": symbol}
            for symbol in symbols for channel in ("books", "ticker", "trade")
        ]
        attempt = 0
        while True:
            try:
                connection_id = f"bitget-{uuid.uuid4().hex}"
                session_started = time.monotonic()
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(json.dumps({"op": "subscribe", "args": args}))
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1_000)
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            continue
                        latency = getattr(socket, "latency", None)
                        payload["_alina_transport"] = {
                            "connection_id": connection_id,
                            "receive_wall_ts_ms": receive_wall_ts_ms,
                            "receive_mono_ns": receive_mono_ns,
                            "transport_rtt_ms": float(latency) * 1_000.0 if isinstance(latency, (int, float)) else None,
                        }
                        yield payload
                        if time.monotonic() - session_started >= self.session_refresh_s:
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = compute_backoff_delay(attempt=attempt, shard_key="bitget-public-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)

__all__=["BitgetMarketState","BitgetPublicClient","parse_bitget_instruments","REST_BASE_URL","PUBLIC_WS_URL"]
