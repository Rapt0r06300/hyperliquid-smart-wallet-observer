"""Tests rapports & visualisation."""
from __future__ import annotations

from hl_observer.backtesting.reporting_extras import (
    daily_report_markdown,
    equity_svg,
    l2_feature_vector,
)


def test_daily_report_is_honest_about_losses():
    md = daily_report_markdown({
        "date": "2026-07-11", "net_usd": -12.5, "wins": 3, "losses": 7,
        "gross_profit": 20.0, "gross_loss": -32.5, "costs_usd": 4.2,
        "refusals": 118, "max_drawdown": 15.0,
        "top_refusal_reasons": {"EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS": 90, "STALE_SIGNAL": 28},
    })
    assert "-12.50 $ (PERTE)" in md              # la perte est affichée, pas maquillée
    assert "30.0 %" in md                        # winrate 3/10
    assert "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS" in md
    assert "0 argent réel" in md


def test_equity_svg_renders_and_flags_loss():
    svg = equity_svg([1000.0, 990.0, 970.0, 960.0])
    assert svg.startswith("<svg") and "polyline" in svg
    assert "#ef4444" in svg                      # rouge : on finit sous le départ
    assert "DD max 40.00" in svg


def test_l2_feature_vector():
    f = l2_feature_vector([(100.0, 8.0)], [(100.1, 2.0)])
    assert f["imbalance"] > 0                    # gros bid -> pression acheteuse
    assert 100.0 < f["micro_price"] < 100.1
    assert f["spread_bps"] > 0
