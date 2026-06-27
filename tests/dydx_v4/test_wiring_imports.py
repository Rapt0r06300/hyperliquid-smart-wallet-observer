from __future__ import annotations


def test_critical_dydx_modules_import() -> None:
    import hyper_smart_observer.dydx_v4.adaptive_risk  # noqa: F401
    import hyper_smart_observer.dydx_v4.build_whale_file  # noqa: F401
    import hyper_smart_observer.dydx_v4.decision_intelligence_v2  # noqa: F401
    import hyper_smart_observer.dydx_v4.leaderboard_import  # noqa: F401
    import hyper_smart_observer.dydx_v4.notional_bridge  # noqa: F401
    import hyper_smart_observer.dydx_v4.runtime_guards  # noqa: F401
    import hyper_smart_observer.dydx_v4.signal_quality  # noqa: F401
    import hyper_smart_observer.dydx_v4.simulation_truth  # noqa: F401
    import hyper_smart_observer.dydx_v4.whale_ranker  # noqa: F401


def test_default_leaderboard_import_paths_include_whale_csv() -> None:
    from hyper_smart_observer.dydx_v4.leaderboard_import import DEFAULT_IMPORT_PATHS

    assert "data/import/dydx_whales.csv" in DEFAULT_IMPORT_PATHS
