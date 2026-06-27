import asyncio

import httpx
import pytest

from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    HyperliquidInfoError,
)
from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.sources.models import SourceStatus


# ---------- fake httpx-like transports ----------

class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _OkClient:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    async def post(self, url, json=None):
        self.calls += 1
        return _Resp(self._data)

    async def aclose(self):
        return None


class _FailClient:
    async def post(self, url, json=None):
        raise httpx.HTTPError("boom")

    async def aclose(self):
        return None


# ---------- recorder unit tests ----------

def test_recorder_unknown_source_not_usable():
    rec = CollectionRecorder()
    assert rec.usable("allMids", now_ms=1000) is False  # deny-by-default: never fetched


def test_recorder_success_is_usable_and_stores_raw():
    rec = CollectionRecorder()
    rec.record_rest(request_type="allMids", response={"BTC": "60000"}, ok=True, now_ms=1000)
    h = rec.health("allMids", now_ms=1500)
    assert h.status == SourceStatus.OK and h.usable
    assert rec.summary(now_ms=1500)["raw_events_stored"] == 1


def test_recorder_dedups_identical_responses_but_counts_each_fetch():
    rec = CollectionRecorder()
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1000)
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1001)
    # identical raw payload deduped in the store...
    assert rec.summary(now_ms=1002)["raw_events_stored"] == 1
    # ...but both fetch attempts recorded for health
    assert rec.health("allMids", now_ms=1002).samples == 2


def test_recorder_down_on_consecutive_errors():
    rec = CollectionRecorder()
    rec.record_rest(request_type="l2Book", response={"x": 1}, ok=True, now_ms=1000)
    for i in range(3):
        rec.record_rest(request_type="l2Book", ok=False, error="timeout", now_ms=2000 + i)
    h = rec.health("l2Book", now_ms=2100)
    assert h.status == SourceStatus.DOWN and not h.usable


def test_recorder_stale_when_last_ok_too_old():
    rec = CollectionRecorder(stale_after_ms=10_000)
    rec.record_rest(request_type="meta", response={"x": 1}, ok=True, now_ms=1000)
    h = rec.health("meta", now_ms=1000 + 20_000)
    assert h.status == SourceStatus.STALE and not h.usable


def test_recorder_never_raises_on_weird_response():
    rec = CollectionRecorder()
    # a non-JSON object must not blow up the recorder
    rec.record_rest(request_type="weird", response=object(), ok=True, now_ms=1)
    assert rec.usable("weird", now_ms=2) is True


def test_recorder_summary_only_reflects_recorded_real_fetches():
    rec = CollectionRecorder()
    assert rec.summary(now_ms=1)["sources"] == 0  # nothing invented
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1000)
    s = rec.summary(now_ms=1001)
    assert s["sources"] == 1 and s["usable"] == 1 and s["raw_events_stored"] == 1


# ---------- real wiring through HyperliquidInfoClient._post_info ----------

def test_rest_client_records_provenance_on_success():
    rec = CollectionRecorder()
    client = HyperliquidInfoClient(client=_OkClient({"BTC": "60000"}), recorder=rec)
    out = asyncio.run(client.all_mids())
    assert out == {"BTC": "60000"}
    h = rec.health("allMids")
    assert h.status == SourceStatus.OK and h.usable
    assert rec.summary()["raw_events_stored"] == 1


def test_rest_client_records_failure_as_down():
    rec = CollectionRecorder()
    client = HyperliquidInfoClient(
        client=_FailClient(), recorder=rec, max_retries=0, backoff_base_seconds=0.0
    )
    with pytest.raises(HyperliquidInfoError):
        asyncio.run(client.all_mids())
    assert rec.usable("allMids") is False  # recorded, never succeeded -> DOWN


def test_rest_client_without_recorder_behaves_unchanged():
    client = HyperliquidInfoClient(client=_OkClient({"ETH": "3000"}))
    assert asyncio.run(client.all_mids()) == {"ETH": "3000"}
