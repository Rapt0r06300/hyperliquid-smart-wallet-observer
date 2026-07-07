from hl_observer.ui.v12_extended_panels import (
    build_cluster_panel, build_copy_fidelity_panel, build_extended_panels,
    build_proxy_health_panel, build_rate_budget_panel,
)


def test_copy_fidelity_empty_then_real():
    assert build_copy_fidelity_panel(None)["empty"] is True
    p = build_copy_fidelity_panel([
        {"side": "long", "leader_price": 100.0, "copy_price": 100.5,
         "leader_ts_ms": 1000, "copy_ts_ms": 1200},
    ])
    assert p["empty"] is False and p["samples"] == 1
    assert p["mean_gap_bps"] == 50.0 and p["mean_lag_ms"] == 200.0  # 0.5% = 50 bps, 200ms lag


def test_cluster_panel_requires_two_wallets():
    assert build_cluster_panel([{"cluster_id": "c1", "wallets": 1}])["empty"] is True
    p = build_cluster_panel([{"cluster_id": "c1", "wallets": 3, "notional_usdc": 1234.5}])
    assert p["count"] == 1 and p["clusters"][0]["wallets"] == 3


def test_proxy_health_panel():
    assert build_proxy_health_panel([])["empty"] is True
    p = build_proxy_health_panel([{"proxy": "p1", "ok": True, "latency_ms": 80},
                                  {"proxy": "p2", "ok": False}])
    assert p["total"] == 2 and p["healthy"] == 1


def test_rate_budget_panel_empty_and_real():
    assert build_rate_budget_panel(used=None, limit=None, window_s=60)["empty"] is True
    p = build_rate_budget_panel(used=300.0, limit=1200.0, window_s=60)
    assert p["remaining"] == 900.0 and p["pct_used"] == 25.0


def test_extended_panels_bundle_keys():
    out = build_extended_panels()
    assert set(out) == {"copy_fidelity", "cluster_detector", "proxy_health", "rate_budget"}
    assert all(out[k]["empty"] for k in out)  # honest empty by default
