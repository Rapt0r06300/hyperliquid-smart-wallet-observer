from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

import hl_observer.hyperliquid.rest_info_client as info
from hl_observer.hyperliquid.schemas import OrderStatusKind


def test_payload_builders_read_only_and_validation() -> None:
    assert info.build_all_mids_payload()=={"type":"allMids"}
    assert info.build_meta_payload()=={"type":"meta"}
    assert info.build_active_asset_ctx_payload("btc")=={"type":"activeAssetCtx","coin":"BTC"}
    assert info.build_l2_book_payload("eth")["coin"]=="ETH"
    assert info.build_open_orders_payload("u")["user"]=="u"
    assert info.build_clearinghouse_state_payload("u")["type"]=="clearinghouseState"
    assert info.build_frontend_open_orders_payload("u")["type"]=="frontendOpenOrders"
    assert info.build_user_fills_payload("u")=={"type":"userFills","user":"u"}
    assert info.build_user_fills_payload("u",True)["aggregateByTime"] is True
    with pytest.raises(ValueError): info.build_user_fills_by_time_payload("u",2,2)
    fills=info.build_user_fills_by_time_payload("u",1,2,True)
    assert fills["startTime"]==1 and fills["endTime"]==2 and fills["aggregateByTime"] is True
    assert info.build_user_twap_slice_fills_payload("u")["type"]=="userTwapSliceFills"
    assert info.build_order_status_payload("u","c")["oid"]=="c"
    assert info.build_portfolio_payload("u")["type"]=="portfolio"
    assert info.build_historical_orders_payload("u")["type"]=="historicalOrders"
    assert info.build_user_funding_payload("u")=={"type":"userFunding","user":"u"}
    assert info.build_user_funding_payload("u",1,2)["endTime"]==2
    assert info.build_user_rate_limit_payload("u")["type"]=="userRateLimit"
    with pytest.raises(ValueError): info.build_funding_history_payload("btc",2,2)
    assert info.build_funding_history_payload("btc",1)=={"type":"fundingHistory","coin":"BTC","startTime":1}
    assert info.build_funding_history_payload("btc",1,2)["endTime"]==2
    assert info.build_predicted_fundings_payload()=={"type":"predictedFundings"}
    with pytest.raises(ValueError): info.build_candle_snapshot_payload("btc","1m",2,2)
    candle=info.build_candle_snapshot_payload("btc","1m",1,2)
    assert candle["req"]["coin"]=="BTC"
    info._ensure_read_only_payload({"type":"allMids"})
    with pytest.raises(info.HyperliquidInfoError): info._ensure_read_only_payload({"type":"not-allowed"})
    assert info.stable_json_hash({"b":2,"a":1})==info.stable_json_hash({"a":1,"b":2})


def test_map_order_status_known_unknown_and_rejected() -> None:
    known=info.map_order_status({"status":"filled","x":1})
    assert known.status==OrderStatusKind.FILLED and known.is_rejected is False and known.raw["x"]==1
    unknown=info.map_order_status({"status":"mystery"})
    assert unknown.status==OrderStatusKind.UNKNOWN
    # Use one canonical rejected enum value rather than guessing strings.
    rejected=next(iter(info.REJECTED_ORDER_STATUSES))
    row=info.map_order_status({"status":rejected.value})
    assert row.status==rejected and row.is_rejected is True
    assert info.map_order_status({"status":123}).status==OrderStatusKind.UNKNOWN


class Limiter:
    def __init__(self): self.calls=0
    async def wait(self): self.calls+=1


class Response:
    def __init__(self,data=None,*,status_exc=None,json_exc=None):
        self.data=data; self.status_exc=status_exc; self.json_exc=json_exc
    def raise_for_status(self):
        if self.status_exc: raise self.status_exc
    def json(self):
        if self.json_exc: raise self.json_exc
        return self.data


class Client:
    def __init__(self,responses): self.responses=list(responses); self.posts=[]; self.closed=False
    async def post(self,url,json):
        self.posts.append((url,json))
        response=self.responses.pop(0)
        if isinstance(response,Exception): raise response
        return response
    async def aclose(self): self.closed=True


class Recorder:
    def __init__(self,raise_=False): self.rows=[]; self.raise_=raise_
    def record_rest(self,**kwargs):
        if self.raise_: raise RuntimeError("recorder down")
        self.rows.append(kwargs)


def test_client_init_context_record_and_post_retry(monkeypatch) -> None:
    with pytest.raises(info.HyperliquidInfoError, match="/info"):
        info.HyperliquidInfoClient("https://x/execution")

    limiter=Limiter(); recorder=Recorder()
    client=Client([
        httpx.ConnectError("offline",request=httpx.Request("POST","https://x/info")),
        Response({"ok":1}),
    ])
    monkeypatch.setattr(info,"assert_info_endpoint_only",lambda url: None)
    sleeps=[]
    async def sleep(value): sleeps.append(value)
    monkeypatch.setattr(info.asyncio,"sleep",sleep)
    c=info.HyperliquidInfoClient("https://x/info",client=client,rate_limiter=limiter,recorder=recorder,max_retries=1,backoff_base_seconds=.5)
    result=asyncio.run(c._post_info("allMids"))
    assert result=={"ok":1} and limiter.calls==2 and sleeps==[.5]
    assert client.posts[0][1]=={"type":"allMids"}
    assert recorder.rows[-1]["ok"] is True

    failing=Client([Response(json_exc=ValueError("bad")),Response(json_exc=ValueError("bad2"))])
    recorder=Recorder()
    c=info.HyperliquidInfoClient("https://x/info",client=failing,rate_limiter=Limiter(),recorder=recorder,max_retries=1,backoff_base_seconds=0)
    with pytest.raises(info.HyperliquidInfoError, match="call failed"):
        asyncio.run(c._post_info("meta"))
    assert recorder.rows[-1]["ok"] is False and "bad2" in recorder.rows[-1]["error"]

    c=info.HyperliquidInfoClient("https://x/info",client=Client([]),recorder=Recorder(raise_=True))
    # recorder failures are absorbed
    c._record_fetch("x",{},ok=True,error=None)
    info.HyperliquidInfoClient("https://x/info",client=Client([]))._record_fetch("x",{},ok=True,error=None)


def test_client_context_creates_and_closes_owned_client(monkeypatch) -> None:
    made=[]
    class Owned(Client):
        def __init__(self,*a,**k): super().__init__([]); made.append(self)
    monkeypatch.setattr(info.httpx,"AsyncClient",Owned)
    c=info.HyperliquidInfoClient("https://x/info")
    async def run():
        async with c as entered:
            assert entered is c and c._client is made[0]
        assert made[0].closed is True
    asyncio.run(run())


def test_typed_methods_success_and_type_failures(monkeypatch) -> None:
    c=info.HyperliquidInfoClient("https://x/info",client=Client([]))
    async def exercise():
        async def set_return(value):
            async def post(*args,**kwargs): return value
            monkeypatch.setattr(c,"_post_info",post)
        await set_return({"BTC":"1"}); assert await c.all_mids()=={"BTC":"1"}
        await set_return({"u":1}); assert (await c.meta())["u"]==1
        await set_return({"x":1}); assert (await c.active_asset_ctx("btc"))["x"]==1
        await set_return({"levels":[]}); assert "levels" in await c.l2_book("btc")
        await set_return([]); assert await c.open_orders("u")==[]
        await set_return({}); assert await c.clearinghouse_state("u")=={}
        await set_return([]); assert await c.frontend_open_orders("u")==[]
        await set_return([]); assert await c.user_fills("u",True)==[]
        await set_return([]); assert await c.user_fills_by_time("u",1,2,True)==[]
        await set_return([]); assert await c.user_twap_slice_fills("u")==[]
        await set_return({"order":{"status":"filled"}}); assert (await c.order_status("u",1)).status==OrderStatusKind.FILLED
        await set_return({"status":"filled"}); assert (await c.order_status("u",1)).status==OrderStatusKind.FILLED
        await set_return({"anything":1}); assert await c.portfolio("u")=={"anything":1}
        await set_return([]); assert await c.historical_orders("u")==[]
        await set_return([]); assert await c.user_funding("u",1,2)==[]
        await set_return({}); assert await c.user_rate_limit("u")=={}
        await set_return([]); assert await c.funding_history("btc",1,2)==[]
        await set_return([]); assert await c.predicted_fundings()==[]
        await set_return({}); assert await c.spot_meta()=={}
        await set_return({}); assert await c.vault_details("v")=={}
        await set_return([]); assert await c.candle_snapshot("btc","1m",1,2)==[]

        checks=[
            (c.all_mids,()),(c.meta,()),(c.active_asset_ctx,("btc",)),(c.l2_book,("btc",)),
            (c.clearinghouse_state,("u",)),(c.user_rate_limit,("u",)),(c.spot_meta,()),(c.vault_details,("v",)),
        ]
        for fn,args in checks:
            await set_return([])
            with pytest.raises(info.HyperliquidInfoError): await fn(*args)
        list_checks=[
            (c.open_orders,("u",)),(c.frontend_open_orders,("u",)),(c.user_fills,("u",)),
            (c.user_fills_by_time,("u",1,2)),(c.user_twap_slice_fills,("u",)),
            (c.historical_orders,("u",)),(c.user_funding,("u",)),(c.funding_history,("btc",1)),
            (c.predicted_fundings,()),(c.candle_snapshot,("btc","1m",1,2)),
        ]
        for fn,args in list_checks:
            await set_return({})
            with pytest.raises(info.HyperliquidInfoError): await fn(*args)
        await set_return([])
        with pytest.raises(info.HyperliquidInfoError): await c.order_status("u",1)
    asyncio.run(exercise())


def test_fill_size_guards_and_iter_pagination(monkeypatch) -> None:
    c=info.HyperliquidInfoClient("https://x/info",client=Client([]))
    async def exercise():
        async def too_many(*args,**kwargs): return [{}]*(info.MAX_USER_FILLS_PAGE_SIZE+1)
        monkeypatch.setattr(c,"_post_info",too_many)
        with pytest.raises(info.HyperliquidInfoError,match="documented"):
            await c.user_fills("u")
        with pytest.raises(info.HyperliquidInfoError,match="documented"):
            await c.user_fills_by_time("u",1,2)
        with pytest.raises(info.HyperliquidInfoError,match="documented"):
            await c.user_twap_slice_fills("u")

        pages=[[{"time":1}],[{"time":3}],[]]
        async def by_time(*args,**kwargs): return pages.pop(0)
        monkeypatch.setattr(c,"user_fills_by_time",by_time)
        got=[]
        async for page in c.iter_user_fills_by_time("u",1,10,page_window_ms=2,max_pages=5): got.append(page)
        assert len(got)==2

        async def no_advance(*args,**kwargs): return [{"time":1}]*info.MAX_USER_FILLS_PAGE_SIZE
        monkeypatch.setattr(c,"user_fills_by_time",no_advance)
        with pytest.raises(info.HyperliquidInfoError,match="cursor did not advance"):
            async for _ in c.iter_user_fills_by_time("u",2,10): pass

        async def no_times(*args,**kwargs): return [{}]*info.MAX_USER_FILLS_PAGE_SIZE
        monkeypatch.setattr(c,"user_fills_by_time",no_times)
        with pytest.raises(info.HyperliquidInfoError,match="without fill timestamps"):
            async for _ in c.iter_user_fills_by_time("u",1,10): pass

        duplicate=[{"time":5}]*info.MAX_USER_FILLS_PAGE_SIZE
        monkeypatch.setattr(c,"user_fills_by_time",lambda *a,**k: None)
        calls={"n":0}
        async def dup(*args,**kwargs): calls["n"]+=1; return duplicate
        monkeypatch.setattr(c,"user_fills_by_time",dup)
        with pytest.raises(info.HyperliquidInfoError,match="Duplicate"):
            async for _ in c.iter_user_fills_by_time("u",1,20,page_window_ms=5): pass

        async def one(*args,**kwargs): return [{"time":1}]
        monkeypatch.setattr(c,"user_fills_by_time",one)
        got=[]
        async for page in c.iter_user_fills_by_time("u",1,20,max_pages=1): got.append(page)
        assert len(got)==1

        with pytest.raises(info.HyperliquidInfoError,match="window did not advance"):
            async for _ in c.iter_user_fills_by_time("u",1,3,page_window_ms=-1): pass
    asyncio.run(exercise())
