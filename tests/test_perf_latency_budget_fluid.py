"""PERF-1/2/3/4/5 + FLUID: latence, budget, garde chemin chaud, deltas UI."""

from __future__ import annotations

from hl_observer.perf.hot_path_guard import audit_hot_path
from hl_observer.perf.latency_budget import recommend_signal_age_gate_ms
from hl_observer.perf.latency_tracker import LatencyTracker
from hl_observer.ui.status_delta import compute_status_delta


def test_latency_tracker_percentiles_per_stage():
    t = LatencyTracker()
    base = 1_000_000.0
    for i in range(100):
        t.record_decision(leader_ms=base, detect_ms=base + 200 + i, decision_ms=base + 260 + i, fill_ms=base + 700 + i)
    rep = t.report()
    assert rep["leader_to_detect"]["n"] == 100
    assert rep["end_to_end"]["p50"] > 0
    assert rep["end_to_end"]["p95"] >= rep["end_to_end"]["p50"]
    assert rep["detect_to_decision"]["p50"] > 0


def test_latency_tracker_ignores_bad_values():
    t = LatencyTracker()
    t.record_stage("leader_to_detect", -5)   # négatif ignoré
    t.record_stage("unknown_stage", 10)      # étage inconnu ignoré
    t.record_stage("leader_to_detect", None)
    assert t.report()["leader_to_detect"]["n"] == 0


def test_budget_recommends_tighter_gate_when_fast_and_abstains_when_scarce():
    t = LatencyTracker()
    scarce = recommend_signal_age_gate_ms(t.report())
    assert scarce["applied"] is False and scarce["recommended_max_signal_age_ms"] is None
    base = 1_000_000.0
    for i in range(60):
        t.record_decision(leader_ms=base, detect_ms=base + 100, decision_ms=base + 140, fill_ms=base + 300)
    rec = recommend_signal_age_gate_ms(t.report())
    assert rec["reason"] == "OK"
    assert rec["applied"] is False  # jamais appliqué en aveugle
    assert 2_000 <= rec["recommended_max_signal_age_ms"] <= 12_000


def test_hot_path_guard_flags_rest_disk_blocking():
    ops = [
        {"name": "ws_read_fills", "stage": "hot"},
        {"name": "requests.get /info", "stage": "hot"},
        {"name": "json.dump snapshot", "stage": "hot"},
        {"name": "time.sleep", "stage": "hot", "blocking": True},
        {"name": "compute_edge", "stage": "hot"},
        {"name": "json.dump export", "stage": "cold"},  # hors tick: OK
    ]
    out = audit_hot_path(ops)
    assert out["clean"] is False
    kinds = {v["kind"] for v in out["violations"]}
    assert "REST_IN_HOT_PATH" in kinds and "DISK_IN_HOT_PATH" in kinds and "BLOCKING" in kinds
    assert out["violation_count"] == 3  # le json.dump 'cold' n'est pas compté


def test_hot_path_clean_when_only_ws_and_compute():
    out = audit_hot_path([{"name": "ws_read", "stage": "hot"}, {"name": "score_leader", "stage": "hot"}])
    assert out["clean"] is True


def test_status_delta_only_reports_changes():
    prev = {"net_pnl_usdt": 1.0, "open_positions": 2, "positions": [{"coin": "HYPE", "side": "LONG", "notional_usdt": 40.0}]}
    same = compute_status_delta(prev, dict(prev))
    assert same["has_changes"] is False
    curr = {"net_pnl_usdt": 1.2, "open_positions": 2, "positions": [{"coin": "HYPE", "side": "LONG", "notional_usdt": 40.0}]}
    d = compute_status_delta(prev, curr)
    assert d["changed_fields"] == {"net_pnl_usdt": 1.2}
    assert d["positions_changed"] is False
    curr2 = {"net_pnl_usdt": 1.2, "open_positions": 3, "positions": curr["positions"] + [{"coin": "BTC", "side": "SHORT", "notional_usdt": 25.0}]}
    d2 = compute_status_delta(curr, curr2)
    assert d2["positions_changed"] is True
