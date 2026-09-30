"""A1: gate composite risque/qualité, flag-gated, deny-by-default OFF."""

from __future__ import annotations

from hl_observer.integration.risk_quality_gate import evaluate_pre_trade

_MARKET = {"l2_depth_usdt": 500_000, "daily_volume_usdt": 200_000_000, "regime": "TRENDING", "volume_zscore": 1.5}
_DATA = {"price": 100.0, "recent_prices": [100, 101, 99.5, 100.2], "prices_by_source": {"hl": 100.0, "bybit": 100.1}, "last_update_ms": 1400, "now_ms": 1500}
_CAL = {"utc_weekday": 2, "utc_hour": 15, "now_ms": 1500, "macro_events_ms": []}


def _call(**over):
    base = dict(coin="BTC", side="LONG", raw_edge_bps=50.0, notional_usdt=25.0,
                open_positions=[], market=dict(_MARKET), data=dict(_DATA), calendar=dict(_CAL))
    base.update(over)
    return evaluate_pre_trade(**base)


def test_all_gates_off_by_default_allows(monkeypatch):
    for f in ("HYPERSMART_GATE_DATA_QUALITY", "HYPERSMART_GATE_REGIME_VOLUME", "HYPERSMART_GATE_MARKET_CLASS", "HYPERSMART_GATE_CALENDAR", "HYPERSMART_GATE_CORRELATION"):
        monkeypatch.delenv(f, raising=False)
    r = _call()
    assert r["allowed"] is True and r["gates_applied"] == []


def test_data_quality_gate_blocks_fat_finger(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GATE_DATA_QUALITY", "1")
    r = _call(data={"price": 300.0, "recent_prices": [100, 101, 99.5], "prices_by_source": {"hl": 300.0, "bybit": 100.0}, "last_update_ms": 1400, "now_ms": 1500})
    assert r["allowed"] is False
    assert any("FAT_FINGER" in x or "CONTRADICT" in x for x in r["reasons"])


def test_regime_ranging_suppresses(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GATE_REGIME_VOLUME", "1")
    r = _call(market={**_MARKET, "regime": "RANGING"})
    assert r["allowed"] is False and "REGIME_RANGING_SUPPRESSED" in r["reasons"]


def test_market_class_min_edge_enforced(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GATE_MARKET_CLASS", "1")
    # long-tail exige 45 bps; edge 30 → refusé
    r = _call(raw_edge_bps=30.0, market={"l2_depth_usdt": 5_000, "daily_volume_usdt": 500_000, "regime": "TRENDING", "volume_zscore": 0.0})
    assert r["allowed"] is False and any("EDGE_BELOW_CLASS_MINIMUM" in x for x in r["reasons"])


def test_correlation_gate_blocks_redundant(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GATE_CORRELATION", "1")
    positions = [{"coin": "SOL", "side": "LONG", "notional_usdt": 40}, {"coin": "AVAX", "side": "LONG", "notional_usdt": 40}, {"coin": "NEAR", "side": "LONG", "notional_usdt": 40}]
    r = _call(coin="APT", side="LONG", open_positions=positions)
    assert r["allowed"] is False and any("CORR" in x for x in r["reasons"])


def test_clean_trade_passes_with_gates_on(monkeypatch):
    for f in ("HYPERSMART_GATE_DATA_QUALITY", "HYPERSMART_GATE_REGIME_VOLUME", "HYPERSMART_GATE_MARKET_CLASS", "HYPERSMART_GATE_CALENDAR", "HYPERSMART_GATE_CORRELATION"):
        monkeypatch.setenv(f, "1")
    r = _call()  # BTC major, trending, edge 50, données propres, pas de corrélation
    assert r["allowed"] is True
    assert "DATA_QUALITY" in r["gates_applied"] and "CORRELATION" in r["gates_applied"]
