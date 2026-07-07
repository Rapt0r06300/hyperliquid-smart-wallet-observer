"""Metagraphe parfait: endpoint equity_history réel + page qui le consomme."""

from __future__ import annotations

from types import SimpleNamespace

from hl_observer.ui.dashboard_v2 import create_dashboard_v2_router


def _endpoint(name):
    router = create_dashboard_v2_router()
    return next(r.endpoint for r in router.routes if r.path == name)


def test_page_uses_real_history_endpoint_and_smoothing():
    html = _endpoint("/v2")().body.decode("utf-8")
    assert "/v2/equity_history" in html          # metagraphe branché sur la vraie courbe
    assert "smoothPath" in html                   # courbe lissée (Catmull-Rom -> Bézier)
    assert "base = equity départ" in html         # ligne de base profit/perte
    assert "METAGRAPHE" in html


def test_equity_history_endpoint_reads_state():
    router = create_dashboard_v2_router()
    ep = next(r.endpoint for r in router.routes if r.path == "/v2/equity_history")
    state = SimpleNamespace(simulation_equity_history=[
        {"timestamp_ms": 1000, "current_equity_usdt": 1000.0, "current_pnl_usdc": 0.0},
        {"timestamp_ms": 2000, "current_equity_usdt": 1001.5, "current_pnl_usdc": 1.5},
    ])
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ui_state=state)))
    import json
    payload = json.loads(ep(req, max=600).body.decode("utf-8"))
    assert payload["count"] == 2
    assert payload["points"][1]["equity"] == 1001.5
    assert payload["read_only"] is True


def test_equity_history_empty_state_is_honest():
    router = create_dashboard_v2_router()
    ep = next(r.endpoint for r in router.routes if r.path == "/v2/equity_history")
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ui_state=None)))
    import json
    payload = json.loads(ep(req, max=600).body.decode("utf-8"))
    assert payload["count"] == 0 and payload["points"] == []
