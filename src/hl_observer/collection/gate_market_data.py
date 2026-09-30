"""Gate.io USDT perpetual public collector (read-only)."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
import httpx
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE, MarketLevel, NativeMarketSnapshot, UNMEASURABLE, canonical_coin

REST_BASE_URL = "https://api.gateio.ws/api/v4"
PUBLIC_WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"

def _f(v: Any) -> float | None:
    try: return float(v)
    except (TypeError, ValueError): return None
def _i(v: Any) -> int | None:
    try: return int(v)
    except (TypeError, ValueError): return None

def parse_gate_contracts(payload: Any) -> list[tuple[str, str]]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = []
    for item in rows or []:
        if not isinstance(item, dict): continue
        symbol = str(item.get("name") or item.get("contract") or "").upper()
        if not symbol or item.get("in_delisting") in (True, "true"): continue
        if str(item.get("type") or "direct").lower() not in {"direct", ""}: continue
        out.append((canonical_coin(symbol), symbol))
    return sorted({x for x in out if x[0]})

@dataclass(slots=True)
class GateMarketState:
    contract: str
    stale_after_ms: int = 1_000
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    sequence: int | None = None
    exchange_ts_ms: int = 0
    receive_ts_ms: int = 0
    quality: str = UNMEASURABLE
    reason: str = "NO_SNAPSHOT"
    last: float | None = None
    mark: float | None = None
    index: float | None = None
    volume_24h: float | None = None
    open_interest: float | None = None
    funding_rate: float | None = None

    def apply_book(self, payload: dict[str, Any], *, receive_ts_ms: int | None = None) -> str:
        seq = _i(payload.get("u") or payload.get("last_update_id") or payload.get("id"))
        if self.sequence is not None and seq is not None and seq > self.sequence + 1:
            self.quality, self.reason = DESYNC, "SEQUENCE_GAP"; return self.quality
        for side, target in ((payload.get("b") or payload.get("bids"), self.bids), (payload.get("a") or payload.get("asks"), self.asks)):
            for row in side or []:
                if isinstance(row, (list, tuple)):
                    price, size = _f(row[0]), _f(row[1])
                elif isinstance(row, dict):
                    price, size = _f(row.get("p") or row.get("price")), _f(row.get("s") or row.get("size"))
                else: continue
                if price is None or price <= 0 or size is None: continue
                (target.pop(price, None) if size <= 0 else target.__setitem__(price, size))
        self.sequence = seq if seq is not None else self.sequence
        self.exchange_ts_ms = _i(payload.get("t") or payload.get("time")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or int(time.time()*1000)
        self.quality = EXPLOITABLE if self._valid() else UNMEASURABLE
        self.reason = "" if self.quality == EXPLOITABLE else "INVALID_BBO"
        return self.quality

    def apply_ticker(self, payload: dict[str, Any]) -> str:
        self.last = _f(payload.get("last") or payload.get("last_price")) or self.last
        self.mark = _f(payload.get("mark_price") or payload.get("mark")) or self.mark
        self.index = _f(payload.get("index_price") or payload.get("index")) or self.index
        self.volume_24h = _f(payload.get("volume_24h_base") or payload.get("volume_24h")) or self.volume_24h
        self.open_interest = _f(payload.get("total_size") or payload.get("open_interest")) or self.open_interest
        self.funding_rate = _f(payload.get("funding_rate")) if payload.get("funding_rate") is not None else self.funding_rate
        return self.quality

    def snapshot(self, *, now_ms: int | None = None, depth: int = 50) -> NativeMarketSnapshot:
        bids = tuple(MarketLevel(p, s) for p, s in sorted(self.bids.items(), reverse=True)[:depth])
        asks = tuple(MarketLevel(p, s) for p, s in sorted(self.asks.items())[:depth])
        return NativeMarketSnapshot.build(venue="gate", coin=canonical_coin(self.contract), exchange_symbol=self.contract, bid=bids[0].price if bids else 0, ask=asks[0].price if asks else 0, bids=bids, asks=asks, exchange_ts_ms=self.exchange_ts_ms, receive_ts_ms=self.receive_ts_ms, now_ms=now_ms, stale_after_ms=self.stale_after_ms, quality=self.quality if self.quality in {DESYNC, UNMEASURABLE} else None, last=self.last, mark=self.mark, index=self.index, volume_24h=self.volume_24h, open_interest=self.open_interest, funding_rate=self.funding_rate, sequence=self.sequence, reason=self.reason)
    def _valid(self) -> bool: return bool(self.bids and self.asks and max(self.bids) <= min(self.asks))

class GatePublicClient:
    def __init__(self, *, rest_base_url: str = REST_BASE_URL, ws_url: str = PUBLIC_WS_URL) -> None: self.rest_base_url, self.ws_url = rest_base_url.rstrip("/"), ws_url
    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0) -> list[tuple[str, str]]:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/futures/usdt/contracts"); response.raise_for_status(); return parse_gate_contracts(response.json())
    async def messages(self, contracts: Iterable[str]):
        import asyncio, json, websockets
        args = [{"channel":"futures.order_book_update","event":"subscribe","payload":[c,"100ms","20"]} for c in contracts]
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
            for msg in args: await socket.send(json.dumps(msg))
            async for raw in socket: yield json.loads(raw)

__all__ = ["GateMarketState", "GatePublicClient", "parse_gate_contracts", "REST_BASE_URL", "PUBLIC_WS_URL"]
