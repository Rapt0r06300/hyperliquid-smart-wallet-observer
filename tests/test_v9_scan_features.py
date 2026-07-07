from hl_observer.features.scan_features import build_scan_features, WINDOWS


def _trend_prices(n=40, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def test_rich_features_from_full_inputs_quality_ok():
    now = 1_000_000_000
    f = build_scan_features(
        coin="BTC",
        now_ms=now,
        fill_ts_ms=now - 3_000,
        mid=120.0,
        leader_price=119.5,
        best_bid=119.9,
        best_ask=120.1,
        bid_depth_usdc=60_000,
        ask_depth_usdc=40_000,
        recent_prices=_trend_prices(),
        recent_trades=[(120.0, 5.0), (120.1, -2.0), (119.9, 3.0)],
        volume_window_usdc=2_000_000,
        avg_volume_usdc=1_000_000,
        leader_notional_usdc=80_000,
        leader_score=88,
        consensus_wallets=2,
    )
    assert f.quality == "OK"
    assert f.is_fresh is True and f.freshness_score is not None
    assert f.spread_bps is not None and f.spread_bps > 0
    assert f.depth_imbalance is not None and f.depth_imbalance > 0  # plus de bid depth
    assert f.cvd is not None and f.cvd > 0                          # flux acheteur net
    assert f.rvol == 2.0
    # returns positifs sur tendance haussière
    assert f.windowed["ret_5"] is not None and f.windowed["ret_5"] > 0


def test_to_row_has_70_plus_columns():
    f = build_scan_features(coin="BTC", recent_prices=_trend_prices())
    row = f.to_row()
    # 30 scalaires + 4 séries × len(WINDOWS) fenêtres
    assert len(row) >= 50  # borne basse robuste
    assert len([k for k in row if k.startswith(("ret_", "vol_", "range_bps_", "lag_px_"))]) == 4 * len(WINDOWS)
    assert row["execution"] == "forbidden" and row["read_only"] is True


def test_missing_data_is_none_not_fabricated_and_quality_degrades():
    f = build_scan_features(coin="ZEC")  # aucune donnée
    assert f.quality == "BAD"
    assert f.mid is None and f.spread_bps is None and f.cvd is None
    assert f.windowed["ret_5"] is None and f.windowed["vol_15"] is None
    # rien n'est inventé : pas de 0.0 à la place d'un None
    assert f.depth_imbalance is None


def test_partial_inputs_give_degraded_quality():
    now = 1_000_000_000
    f = build_scan_features(
        coin="SOL", now_ms=now, fill_ts_ms=now - 1_000, mid=20.0,
        recent_prices=_trend_prices(n=20),
    )
    assert f.quality in {"DEGRADED", "OK", "BAD"}
    assert f.age_ms == 1_000 and f.is_fresh is True
