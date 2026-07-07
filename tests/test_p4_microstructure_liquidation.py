"""P4: microstructure (OBI/gros trades/anti-rafale) + carte des liquidations."""

from __future__ import annotations

from hl_observer.signals.liquidation_map import (
    estimate_clusters, post_cascade_momentum, proximity_open_refusal,
)
from hl_observer.signals.microstructure import (
    AntiBurstGate, big_trade_boost, obi_confirms, order_book_imbalance,
)


def test_obi_and_confirmation():
    assert order_book_imbalance(80_000, 20_000) == 0.6   # pression acheteuse
    assert obi_confirms("LONG", 80_000, 20_000, threshold=0.10)["confirmed"] is True
    assert obi_confirms("SHORT", 80_000, 20_000, threshold=0.10)["confirmed"] is False
    assert obi_confirms("LONG", 50_000, 50_000)["reason"] == "OBI_AGAINST_OR_NEUTRAL"


def test_big_trade_boost_only_when_aligned():
    trades = [{"notional_usd": 80_000, "side": "LONG"}, {"notional_usd": 10_000, "side": "LONG"}]
    assert big_trade_boost(trades, "LONG")["boost"] == 1.2
    assert big_trade_boost(trades, "SHORT")["boost"] == 1.0   # aucun gros trade short
    assert big_trade_boost([], "LONG")["boost"] == 1.0


def test_anti_burst_gate_blocks_rafale():
    g = AntiBurstGate(cooldown_sec=2.0)
    assert g.allow("HYPE", "LONG", 1000) is True
    assert g.allow("HYPE", "LONG", 1500) is False   # < 2s après
    assert g.allow("HYPE", "LONG", 3200) is True    # > 2s
    assert g.allow("BTC", "LONG", 1500) is True      # autre coin, indépendant


def test_liquidation_clusters_and_proximity_gate():
    buckets = [
        {"liq_price": 99.0, "notional_usd": 5_000_000, "side": "LONG"},
        {"liq_price": 105.0, "notional_usd": 3_000_000, "side": "SHORT"},
        {"liq_price": 98.0, "notional_usd": 500_000, "side": "LONG"},   # sous le seuil
    ]
    clusters = estimate_clusters(buckets, min_notional_usd=1_000_000)
    assert len(clusters) == 2
    assert clusters[0].notional_at_risk_usd == 5_000_000  # trié par taille
    # ouvrir LONG à 100 avec une cascade de longs à 99 juste dessous → refus
    r = proximity_open_refusal("LONG", 100.0, clusters, danger_pct=1.5)
    assert r == "LIQ_CASCADE_BELOW_AGAINST_LONG"
    # loin de tout cluster → OK
    assert proximity_open_refusal("LONG", 110.0, clusters, danger_pct=1.0) == ""


def test_post_cascade_momentum_bias():
    events = [{"liquidated_usd": 3_000_000, "side": "LONG", "ts_ms": 5000}]
    sig = post_cascade_momentum(events, min_liq_usd=2_000_000)
    assert sig["signal"] is True and sig["bias"] == "LONG"   # rebond contrarian après liq de longs
    assert post_cascade_momentum([], )["signal"] is False
