from __future__ import annotations

import asyncio

from fastapi import Response

from hl_observer.ui.dydx_routes import DISCLAIMER, create_dydx_router
from hyper_smart_observer.dydx_v4 import engine as dydx_engine
from hyper_smart_observer.dydx_v4 import simulation_truth


def _endpoints(router):
    return {route.path: route.endpoint for route in router.routes}


class _Engine:
    def __init__(self) -> None:
        self.closed_limit = None
        self.refused_limit = None
        self.whale_limit = None

    def get_status(self):
        return {
            "session_id": "s1",
            "net_pnl_usdt": 1.25,
            "equity_usdt": 1001.25,
            "total_trades": 4,
            "winrate": "50%",
            "fees_paid": 0.2,
            "open_positions": 1,
            "running": True,
            "rest_healthy": True,
            "last_error": "DISCOVERY_RUNNING",
            "wallets_in_shortlist": 7,
            "iteration": 9,
        }

    def get_wallets(self):
        return [{"address": "dydx1"}]

    def get_open_positions(self):
        return [{"market": "BTC-USD"}]

    def get_closed_trades(self, *, limit):
        self.closed_limit = limit
        return [{"id": 1}]

    def get_refused_decisions(self, *, limit):
        self.refused_limit = limit
        return [{"reason": "NO_EDGE"}]

    def get_mark_prices(self):
        return {"BTC-USD": 100.0}

    def get_realtime_tick(self):
        return {"running": True, "paper_only": True}

    def get_whale_stats(self):
        return {
            "enabled": True,
            "total_tracked": 5,
            "hot_set_size": 2,
            "candidates_known": 8,
            "last_refresh_ms": 123,
            "refresh_count": 3,
            "avg_win_rate": 0.4567,
            "avg_pnl_usdc": 12.345,
        }

    def get_whale_top(self, *, n):
        self.whale_limit = n
        return [{"rank": i} for i in range(120)]


def test_dydx_routes_success_paths(monkeypatch) -> None:
    eng = _Engine()
    monkeypatch.setattr(dydx_engine, "get_engine", lambda: eng)
    monkeypatch.setattr(simulation_truth, "truth_report", lambda: {"read_only": True, "paper_only": True})
    endpoints = _endpoints(create_dydx_router())

    assert asyncio.run(endpoints["/api/dydx/status"]())["running"] is True
    assert asyncio.run(endpoints["/api/dydx/wallets"]()) == [{"address": "dydx1"}]
    assert asyncio.run(endpoints["/api/dydx/positions"]()) == [{"market": "BTC-USD"}]
    assert asyncio.run(endpoints["/api/dydx/trades"](999)) == [{"id": 1}]
    assert eng.closed_limit == 200
    assert asyncio.run(endpoints["/api/dydx/refused"](999)) == [{"reason": "NO_EDGE"}]
    assert eng.refused_limit == 500
    assert asyncio.run(endpoints["/api/dydx/prices"]()) == {"BTC-USD": 100.0}

    pnl = asyncio.run(endpoints["/api/dydx/pnl"]())
    assert pnl["session_id"] == "s1"
    assert pnl["net_pnl_usdt"] == 1.25
    assert pnl["disclaimer"] == DISCLAIMER

    truth = asyncio.run(endpoints["/api/dydx/simulation-truth"]())
    assert truth["read_only"] is True
    assert truth["disclaimer"] == DISCLAIMER

    response = Response()
    tick = asyncio.run(endpoints["/api/dydx/realtime-tick"](response))
    assert tick["running"] is True
    assert response.headers["Cache-Control"].startswith("no-store")
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Hypersmart-Mode"] == "paper-read-only"

    health = asyncio.run(endpoints["/api/dydx/health"]())
    assert health["discovery"] == "running"
    assert health["wallets"] == 7

    whales = asyncio.run(endpoints["/api/dydx/whales"](150))
    assert eng.whale_limit == 100
    assert whales["enabled"] is True
    assert whales["avg_win_rate"] == 0.457
    assert whales["avg_pnl_usdc"] == 12.35
    assert len(whales["top"]) == 120


def test_dydx_health_idle_branch(monkeypatch) -> None:
    eng = _Engine()
    status = eng.get_status()
    status["last_error"] = ""
    monkeypatch.setattr(eng, "get_status", lambda: status)
    monkeypatch.setattr(dydx_engine, "get_engine", lambda: eng)
    endpoints = _endpoints(create_dydx_router())
    assert asyncio.run(endpoints["/api/dydx/health"]())["discovery"] == "idle"


def test_dydx_routes_fail_closed_paths(monkeypatch) -> None:
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(dydx_engine, "get_engine", boom)
    endpoints = _endpoints(create_dydx_router())

    assert asyncio.run(endpoints["/api/dydx/status"]())["running"] is False
    assert asyncio.run(endpoints["/api/dydx/wallets"]()) == []
    assert asyncio.run(endpoints["/api/dydx/positions"]()) == []
    assert asyncio.run(endpoints["/api/dydx/trades"](1)) == []
    assert asyncio.run(endpoints["/api/dydx/refused"](1)) == []
    assert asyncio.run(endpoints["/api/dydx/prices"]()) == {}
    assert "offline" in asyncio.run(endpoints["/api/dydx/pnl"]())["error"]

    response = Response()
    tick = asyncio.run(endpoints["/api/dydx/realtime-tick"](response))
    assert tick["running"] is False
    assert tick["paper_only"] is True
    assert tick["read_only"] is True
    assert tick["equity_usdt"] == 1000.0

    health = asyncio.run(endpoints["/api/dydx/health"]())
    assert health["running"] is False
    assert "offline" in health["error"]

    whales = asyncio.run(endpoints["/api/dydx/whales"](20))
    assert whales["enabled"] is False
    assert "offline" in whales["error"]


def test_dydx_simulation_truth_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(dydx_engine, "get_engine", lambda: _Engine())

    def boom_truth():
        raise RuntimeError("truth unavailable")

    monkeypatch.setattr(simulation_truth, "truth_report", boom_truth)
    endpoints = _endpoints(create_dydx_router())
    truth = asyncio.run(endpoints["/api/dydx/simulation-truth"]())
    assert truth["read_only"] is True
    assert truth["paper_only"] is True
    assert "truth unavailable" in truth["error"]
    assert truth["disclaimer"] == DISCLAIMER
