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
    assert "EQUITY //" in html   # panneau courbe (ex-"METAGRAPHE", renomme a la refonte /v2)


def _isolate_persisted_store(monkeypatch):
    """L'endpoint privilegie l'historique PERSISTE (survit a la fermeture du navigateur).
    En test, ce store lisait les VRAIES donnees runtime -> le test n'etait pas isole (600 points
    au lieu de 0). On neutralise le store pour tester la lecture de l'etat en memoire."""
    monkeypatch.setattr(
        "hl_observer.runtime.equity_history_store.read_equity_points",
        lambda max=600: [],
    )
    # 19/07 — MÊME PIÈGE, DEUXIÈME FOIS. La courbe d'equity inclut désormais le net CARRY (elle
    # affichait 1 000,00 plat pendant que le bandeau disait -5,00 : deux vérités pour un seul
    # PnL). Sans cette isolation, le vrai PnL carry du runtime entrait dans le test et le
    # décalait. Un test qui lit l'état live ne teste pas, il constate.
    monkeypatch.setattr("hl_observer.ui.dashboard_v2.net_carry_courant", lambda root=None: 0.0)


def test_equity_history_endpoint_reads_state(monkeypatch):
    _isolate_persisted_store(monkeypatch)
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


def test_equity_history_empty_state_is_honest(monkeypatch):
    _isolate_persisted_store(monkeypatch)
    router = create_dashboard_v2_router()
    ep = next(r.endpoint for r in router.routes if r.path == "/v2/equity_history")
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ui_state=None)))
    import json
    payload = json.loads(ep(req, max=600).body.decode("utf-8"))
    assert payload["count"] == 0 and payload["points"] == []
