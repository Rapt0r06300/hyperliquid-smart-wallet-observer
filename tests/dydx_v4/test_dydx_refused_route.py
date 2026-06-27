from __future__ import annotations

from hl_observer.ui.dydx_routes import create_dydx_router


def test_dydx_refused_route_is_registered_read_only() -> None:
    router = create_dydx_router()
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in router.routes
    }

    assert "/api/dydx/refused" in routes
    assert routes["/api/dydx/refused"] == {"GET"}


def test_dydx_realtime_tick_route_is_registered_read_only() -> None:
    router = create_dydx_router()
    routes = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in router.routes
    }

    assert "/api/dydx/realtime-tick" in routes
    assert routes["/api/dydx/realtime-tick"] == {"GET"}
