"""A3: détecteurs grinder (funding cross-venue, confirmation micro+liq, grid)."""

from __future__ import annotations

from hl_observer.integration.grinder_detectors import (
    build_grid_plan, confirm_entry, detect_grinder_opportunities,
)


def test_cross_venue_detector_gated_and_ranks(monkeypatch):
    rates = {"HYPE": {"hl": 8.0, "bybit": 1.0}, "BTC": {"hl": 3.0, "bybit": 2.8}}
    prices = {"HYPE": 40.0, "BTC": 60_000.0}
    monkeypatch.delenv("HYPERSMART_DETECT_CROSS_VENUE_FUNDING", raising=False)
    assert detect_grinder_opportunities(funding_rates_by_coin=rates, prices=prices)["count"] == 0
    monkeypatch.setenv("HYPERSMART_DETECT_CROSS_VENUE_FUNDING", "1")
    out = detect_grinder_opportunities(funding_rates_by_coin=rates, prices=prices)
    assert out["count"] == 1                     # HYPE édge net; BTC trop fin
    assert out["candidates"][0]["coin"] == "HYPE"
    assert out["candidates"][0]["real_execution"] is False


def test_confirm_entry_microstructure_blocks_against_obi(monkeypatch):
    monkeypatch.setenv("HYPERSMART_CONFIRM_MICROSTRUCTURE", "1")
    r = confirm_entry(side="LONG", bid_depth_usdt=20_000, ask_depth_usdt=80_000, recent_trades=[], entry_price=100.0)
    assert r["confirmed"] is False and "OBI_AGAINST" in r["block_reasons"]
    ok = confirm_entry(side="LONG", bid_depth_usdt=80_000, ask_depth_usdt=20_000,
                       recent_trades=[{"notional_usd": 80_000, "side": "LONG"}], entry_price=100.0)
    assert ok["confirmed"] is True and ok["signal_boost"] == 1.2


def test_confirm_entry_liquidation_proximity_gate(monkeypatch):
    monkeypatch.setenv("HYPERSMART_GATE_LIQUIDATION_PROXIMITY", "1")
    oi = [{"liq_price": 99.0, "notional_usd": 5_000_000, "side": "LONG"}]
    r = confirm_entry(side="LONG", bid_depth_usdt=1, ask_depth_usdt=1, recent_trades=[], entry_price=100.0, oi_buckets=oi)
    assert r["confirmed"] is False and any("LIQ_CASCADE" in x for x in r["block_reasons"])


def test_grid_plan_gated(monkeypatch):
    monkeypatch.delenv("HYPERSMART_GRID_PAPER", raising=False)
    assert build_grid_plan(mid_price=100.0)["ok"] is False
    monkeypatch.setenv("HYPERSMART_GRID_PAPER", "1")
    g = build_grid_plan(mid_price=100.0, side="LONG")
    assert g["ok"] is True and g["anti_martingale"] is True
