import pytest

from hl_observer.sources.models import (
    FetchProvenance,
    SourceDefinition,
    SourceKind,
    SourceStatus,
)
from hl_observer.sources.registry import SourceRegistry


def _def(sid="hl_allmids", enabled=True):
    return SourceDefinition(
        source_id=sid, kind=SourceKind.HL_INFO_REST,
        endpoint_or_channel="/info:allMids", description="HL mids", enabled=enabled,
    )


def _prov(sid="hl_allmids", rid="r1", ts=1000, ok=True, quality="OK", error=None):
    return FetchProvenance(source_id=sid, request_id=rid, fetched_at_ms=ts, ok=ok,
                           data_quality=quality, error=error, item_count=10)


def test_register_and_definitions():
    reg = SourceRegistry()
    reg.register(_def())
    assert reg.is_registered("hl_allmids")
    assert [d.source_id for d in reg.definitions()] == ["hl_allmids"]


def test_read_only_enforced():
    with pytest.raises(ValueError):
        SourceDefinition(source_id="x", kind=SourceKind.HL_WS, endpoint_or_channel="ws", read_only=False)


def test_unknown_source_not_usable():
    reg = SourceRegistry()
    reg.register(_def())
    h = reg.health("hl_allmids", now_ms=2000)
    assert h.status == SourceStatus.UNKNOWN and not h.usable
    assert not reg.is_usable("hl_allmids", now_ms=2000)


def test_fresh_ok_is_usable():
    reg = SourceRegistry(stale_after_ms=60_000)
    reg.register(_def())
    reg.record_fetch(_prov(ts=1000))
    h = reg.health("hl_allmids", now_ms=1500)
    assert h.status == SourceStatus.OK and h.usable
    assert reg.is_usable("hl_allmids", now_ms=1500)


def test_stale_when_last_ok_too_old():
    reg = SourceRegistry(stale_after_ms=10_000)
    reg.register(_def())
    reg.record_fetch(_prov(ts=1000))
    h = reg.health("hl_allmids", now_ms=1000 + 20_000)  # 20s > 10s
    assert h.status == SourceStatus.STALE and not h.usable


def test_down_on_consecutive_errors():
    reg = SourceRegistry(down_consecutive_errors=3)
    reg.register(_def())
    reg.record_fetch(_prov(rid="r0", ts=1000, ok=True))
    for i in range(3):
        reg.record_fetch(_prov(rid=f"e{i}", ts=2000 + i, ok=False, error="timeout"))
    h = reg.health("hl_allmids", now_ms=2100)
    assert h.status == SourceStatus.DOWN and not h.usable
    assert h.consecutive_errors == 3
    assert h.last_error == "timeout"


def test_down_when_never_succeeded():
    reg = SourceRegistry()
    reg.register(_def())
    reg.record_fetch(_prov(ok=False, error="boom"))
    h = reg.health("hl_allmids", now_ms=1100)
    assert h.status == SourceStatus.DOWN


def test_degraded_on_low_success_rate():
    reg = SourceRegistry(down_consecutive_errors=99, degraded_success_rate=0.80)
    reg.register(_def())
    # 3 ok, 2 errors interleaved (last is ok so not "down"), rate 0.6 < 0.8
    reg.record_fetch(_prov(rid="a", ts=1000, ok=True))
    reg.record_fetch(_prov(rid="b", ts=1001, ok=False, error="x"))
    reg.record_fetch(_prov(rid="c", ts=1002, ok=True))
    reg.record_fetch(_prov(rid="d", ts=1003, ok=False, error="x"))
    reg.record_fetch(_prov(rid="e", ts=1004, ok=True))
    h = reg.health("hl_allmids", now_ms=1005)
    assert h.status == SourceStatus.DEGRADED and h.usable  # degraded still usable


def test_degraded_on_bad_quality():
    reg = SourceRegistry()
    reg.register(_def())
    reg.record_fetch(_prov(ts=1000, ok=True, quality="DEGRADED"))
    h = reg.health("hl_allmids", now_ms=1100)
    assert h.status == SourceStatus.DEGRADED


def test_dedupe_duplicate_request_id():
    reg = SourceRegistry()
    reg.register(_def())
    assert reg.record_fetch(_prov(rid="same", ts=1000)) is True
    assert reg.record_fetch(_prov(rid="same", ts=1001)) is False  # duplicate ignored
    assert reg.health("hl_allmids", now_ms=1100).samples == 1


def test_disabled_source_not_usable_even_if_fresh():
    reg = SourceRegistry()
    reg.register(_def(enabled=False))
    reg.record_fetch(_prov(ts=1000))
    assert not reg.is_usable("hl_allmids", now_ms=1100)


def test_all_health_lists_every_source():
    reg = SourceRegistry()
    reg.register(_def("a"))
    reg.register(_def("b"))
    reg.record_fetch(_prov(sid="a", ts=1000))
    rows = reg.all_health(now_ms=1100)
    assert {r.source_id for r in rows} == {"a", "b"}


def test_registry_has_no_execution_surface():
    import hl_observer.sources.registry as m
    pub = {n for n in dir(SourceRegistry) if not n.startswith("_")}
    for bad in ("submit", "place", "order", "sign", "send", "execute", "fetch_real"):
        assert not any(bad in n.lower() for n in pub)
