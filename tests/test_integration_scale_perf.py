"""A4: runtime scale/perf (plan de scan à budget, latence, deltas UI)."""

from __future__ import annotations

import hl_observer.integration.scale_perf_runtime as spr
from hl_observer.integration.scale_perf_runtime import (
    latency_snapshot, plan_scan_cycle, push_latency, ui_delta,
)


def _reset_budget():
    spr._BUDGET = None  # isole le singleton entre tests


def test_scan_cycle_caps_ws_and_respects_budget():
    _reset_budget()
    scored = {f"0x{i:03d}": float(1000 - i) for i in range(300)}
    last_seen = {w: 0 for w in scored}
    cycle = plan_scan_cycle(scored_wallets=scored, last_seen_ms=last_seen, now_ms=200_000, max_ws=10)
    assert cycle["ws_subscribed"] == 10                      # contrainte HL
    assert cycle["rest_due"] > 0
    assert cycle["budget"]["denied"] >= 0
    # granted + deferred = due (rien perdu)
    assert len(cycle["rest_granted"]) + len(cycle["rest_deferred"]) == cycle["rest_due"]


def test_budget_defers_when_exhausted():
    _reset_budget()
    # petit budget: beaucoup de wallets dûs → certains temporisés (pas de 429)
    spr._BUDGET = spr.ApiBudget(capacity=5, refill_per_sec=0)
    scored = {f"0x{i:03d}": float(500 - i) for i in range(60)}
    last_seen = {w: 0 for w in scored}
    cycle = plan_scan_cycle(scored_wallets=scored, last_seen_ms=last_seen, now_ms=20_000, max_ws=10, items_per_wallet=20)
    assert len(cycle["rest_deferred"]) > 0                   # backoff au lieu de 429


def test_latency_tracker_singleton_records():
    for i in range(40):
        push_latency(leader_ms=0, detect_ms=200 + i, decision_ms=250 + i, fill_ms=600 + i)
    rep = latency_snapshot()
    assert rep["end_to_end"]["n"] >= 40 and rep["end_to_end"]["p95"] > 0


def test_ui_delta_incremental():
    prev = {"net_pnl_usdt": 1.0, "open_positions": 2, "positions": []}
    curr = {"net_pnl_usdt": 1.5, "open_positions": 2, "positions": []}
    d = ui_delta(prev, curr)
    assert d["changed_fields"] == {"net_pnl_usdt": 1.5} and d["has_changes"] is True
