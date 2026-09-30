import json

from hl_observer.agent_tools import readonly_inspectors as ins
from hl_observer.agent_tools.manifest import READ_TOOLS, validate_agent_tool_manifest
from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate
from hl_observer.sources.collection_recorder import CollectionRecorder


def test_implemented_tools_are_declared_in_manifest():
    validate_agent_tool_manifest()  # manifest itself is valid / agent-safe
    assert set(ins.IMPLEMENTED_READ_TOOLS).issubset(set(READ_TOOLS))


def test_source_health_empty_is_honest():
    p = ins.source_health_read(None)
    assert p["empty"] is True and p["sources"] == 0
    json.dumps(p)  # JSON-serializable


def test_source_health_reflects_real_recorder():
    rec = CollectionRecorder()
    rec.record_rest(request_type="allMids", response={"BTC": "60000"}, ok=True, now_ms=1000)
    p = ins.source_health_read(rec, now_ms=1500)
    assert p["sources"] == 1 and p["usable"] == 1 and p["raw_events_stored"] == 1
    assert p["all_health"][0]["source_id"] == "hl_info:allMids"
    json.dumps(p)


def test_dashboard_export_composes_three_reads():
    rec = CollectionRecorder()
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1000)
    decisions = [evaluate_copy_candidate(CopyInputs(signal_age_ms=99999)),  # SIGNAL_TOO_OLD
                 evaluate_copy_candidate(CopyInputs(source_usable=True, signal_age_ms=1000,
                                                    net_edge_bps=25.0, min_edge_bps=10.0))]
    out = ins.dashboard_export(recorder=rec,
                               raw_reasons=["REJECT_TOO_LATE", "STALE_SIGNAL"],
                               decisions=decisions, now_ms=2000)
    assert set(out) == {"tool", "source_health", "no_trade", "funnel"}
    assert out["source_health"]["sources"] == 1
    assert out["no_trade"]["recognized"] == 2  # both map to SIGNAL_TOO_OLD
    assert out["funnel"]["total"] == 2
    json.dumps(out)  # whole export is JSON-serializable


def test_no_execution_surface():
    pub = [n for n in dir(ins) if not n.startswith("_")]
    for bad in ("submit", "place", "order", "sign", "send", "execute", "deposit", "withdraw"):
        assert not any(bad in n.lower() for n in pub)
