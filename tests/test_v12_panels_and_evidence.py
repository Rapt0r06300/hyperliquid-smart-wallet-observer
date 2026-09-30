import json

from hl_observer.evidence.no_trade_evidence import no_trade_evidence_row
from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate
from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.ui.v12_panels import build_no_trade_panel, build_v12_panels


def test_no_trade_panel_accepts_count_list_from_routes():
    # routes.py format: list of {"reason","count"}
    counts = [{"reason": "REJECT_TOO_LATE", "count": 2}, {"reason": "LIQUIDITY_TOO_LOW", "count": 1}]
    panel = build_no_trade_panel(counts)
    codes = {r["reason_code"]: r["count"] for r in panel["by_code"]}
    assert codes["SIGNAL_TOO_OLD"] == 2 and codes["LIQUIDITY_TOO_LOW"] == 1
    assert panel["recognized"] == 3


def test_no_trade_panel_accepts_dict_counts():
    panel = build_no_trade_panel({"MID_MISSING": 3})
    assert panel["by_code"][0]["reason_code"] == "MID_MISSING"
    assert panel["by_code"][0]["count"] == 3


def test_build_v12_panels_composes_all(monkeypatch):
    rec = CollectionRecorder()
    rec.record_rest(request_type="allMids", response={"BTC": "1"}, ok=True, now_ms=1000)
    decisions = [evaluate_copy_candidate(CopyInputs(signal_age_ms=99999)),
                 evaluate_copy_candidate(CopyInputs(signal_age_ms=1000, net_edge_bps=25.0, min_edge_bps=10.0))]
    panels = build_v12_panels(recorder=rec, reason_counts={"SIGNAL_TOO_OLD": 1},
                              decisions=decisions, now_ms=2000)
    assert panels["source_health"]["sources"] == 1
    assert panels["no_trade_explorer"]["recognized"] == 1
    assert panels["decision_funnel"]["total"] == 2
    json.dumps(panels)  # JSON-serializable for the dashboard


def test_no_trade_evidence_row_has_taxonomy_attrs():
    row = no_trade_evidence_row("REJECT_TOO_LATE", wallet="0xabc", coin="BTC", now_ms=123)
    assert row["reason_code"] == "SIGNAL_TOO_OLD"  # alias resolved
    assert row["severity"] == "BLOCK" and row["is_retriable"] is False
    for k in ("reason_code", "severity", "is_retriable", "missing_data",
              "next_action", "evidence_refs", "dashboard_message", "wallet", "coin", "run_context"):
        assert k in row
    json.dumps(row)
