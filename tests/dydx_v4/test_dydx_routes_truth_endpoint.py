from __future__ import annotations


def test_dydx_routes_registers_simulation_truth_endpoint() -> None:
    from src.hl_observer.ui.dydx_routes import create_dydx_router

    router = create_dydx_router()
    paths = {route.path for route in router.routes}

    assert "/api/dydx/simulation-truth" in paths
