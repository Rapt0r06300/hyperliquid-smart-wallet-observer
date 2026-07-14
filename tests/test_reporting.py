"""Tests reporting & attribution."""
from __future__ import annotations

import csv

from hl_observer.backtesting.reporting import (
    ab_compare,
    cost_attribution,
    export_csv,
    reconcile_pnl,
    refusal_stats,
)


def test_export_csv_roundtrip(tmp_path):
    rows = [{"coin": "BTC", "net": 1.5}, {"coin": "ETH", "net": -0.5}]
    p = export_csv(rows, str(tmp_path / "out.csv"))
    with open(p, encoding="utf-8") as f:
        back = list(csv.DictReader(f))
    assert len(back) == 2 and back[0]["coin"] == "BTC"


def test_reconcile_pnl_detects_divergence():
    ok = reconcile_pnl({"cash_balance_usdc": 900.0, "unrealized_pnl_usdc": 50.0, "equity_usdc": 950.0})
    bad = reconcile_pnl({"cash_balance_usdc": 900.0, "unrealized_pnl_usdc": 50.0, "equity_usdc": 999.0})
    assert ok["ok"] is True
    assert bad["ok"] is False and abs(bad["diff"] - 49.0) < 1e-9


def test_cost_attribution_shows_where_money_goes():
    trades = [{"gross": 10.0, "fees": 1.0, "spread": 2.0, "slippage": 0.5, "degradation": 6.5}]
    a = cost_attribution(trades)
    assert abs(a["net"] - 0.0) < 1e-9                     # 10 - 10 = 0
    assert a["cost_share"]["degradation"] > a["cost_share"]["fees"]   # la dégradation domine


def test_refusal_stats_counts():
    stats = refusal_stats([["STALE", "EDGE_LOW"], ["STALE"], ["STALE", "LIQ_LOW"]])
    assert stats[0] == ("STALE", 3)


def test_ab_compare_delta():
    out = ab_compare({"net": 10.0}, {"net": 25.0})
    assert out[0]["delta"] == 15.0
