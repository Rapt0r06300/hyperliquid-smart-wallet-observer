"""G5/G7/G8 + H1/H4/H5/H6 + I1-I5 — réalisme exécution, risque portefeuille, métriques.
Pur / paper / read-only."""

from hl_observer.backtest.execution_realism import (
    adverse_selection_penalty_bps,
    latency_jitter_ms,
    maker_fill_probability,
)
from hl_observer.backtest.pnl_metrics_ext import (
    attribution_by,
    calmar,
    hit_rate_expectancy,
    mae_mfe_stats,
    sharpe,
    sortino,
)
from hl_observer.risk.portfolio_risk import (
    data_anomaly,
    exposure_within_caps,
    gross_net_exposure,
    risk_per_trade_notional,
    vol_target_size_pct,
)


# G5/G7/G8
def test_execution_realism():
    assert maker_fill_probability(queue_ahead_notional=0, incoming_flow_notional=100) > 0.8
    assert maker_fill_probability(queue_ahead_notional=900, incoming_flow_notional=100) < 0.2
    assert maker_fill_probability(queue_ahead_notional=100, incoming_flow_notional=0) == 0.0
    assert adverse_selection_penalty_bps(20.0, toxicity=0.5) == 10.0
    assert latency_jitter_ms(1000, jitter_frac=0.3, sample=1.0) == 1300.0
    assert latency_jitter_ms(1000, jitter_frac=0.3, sample=0.0) == 700.0


# H1/H4/H5/H6
def test_portfolio_risk():
    exp = gross_net_exposure([(100, "long"), (60, "short")])
    assert exp["gross"] == 160.0 and exp["net"] == 40.0
    assert exposure_within_caps(160, 40, max_gross=200, max_net_abs=50) is True
    assert exposure_within_caps(160, 40, max_gross=100, max_net_abs=50) is False
    # vol target: cible 30 / actif 60 -> 0.05*0.5 = 0.025
    assert vol_target_size_pct(30, 60, base_pct=0.05) == 0.025
    # risque 1% de 1000 = 10$, stop 100 bps (1%) -> notionnel 1000
    assert risk_per_trade_notional(1000, 1.0, 100) == 1000.0
    assert data_anomaly(100, 130, max_jump_pct=20) is True
    assert data_anomaly(100, 105, max_jump_pct=20) is False


# I1-I5
def test_metrics_ext():
    rets = [1.0, -0.5, 2.0, -1.0, 1.5]
    assert sharpe(rets) != 0.0
    assert sortino([1.0, 2.0, 3.0]) == float("inf")   # aucune perte
    assert calmar(10.0, 5.0) == 2.0
    attr = attribution_by([{"coin": "ETH", "pnl": -2.0}, {"coin": "BTC", "pnl": 3.0},
                           {"coin": "ETH", "pnl": 0.5}], "coin")
    assert list(attr.keys())[0] == "ETH" and attr["ETH"] == -1.5   # pire d'abord
    stats = mae_mfe_stats([{"mae_bps": 10, "mfe_bps": 50}, {"mae_bps": 30, "mfe_bps": 20}])
    assert stats["avg_mae_bps"] == 20.0 and stats["avg_mfe_bps"] == 35.0
    hr = hit_rate_expectancy([2.0, -1.0, 3.0, -1.0])
    assert hr["hit_rate"] == 0.5 and hr["expectancy"] == 0.75
