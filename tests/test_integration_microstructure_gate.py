"""Câblage anti adverse-selection: microstructure_entry_gate + toxicité live."""

from __future__ import annotations

import hl_observer.integration.grinder_detectors as gd
from hl_observer.integration.grinder_detectors import (
    microstructure_entry_gate, record_fill_markout,
)


def _reset():
    gd._TOX = None


def test_gate_off_by_default_passes(monkeypatch):
    _reset()
    monkeypatch.delenv("HYPERSMART_MICROSTRUCTURE_GATE", raising=False)
    r = microstructure_entry_gate(coin="HYPE", side="LONG", intended_price=100.0,
                                  bid=99.9, ask=100.1, bid_size=100, ask_size=900, base_min_edge_bps=28)
    assert r["allowed"] is True and r["applied"] is False


def test_gate_refuses_micro_adverse(monkeypatch):
    _reset()
    monkeypatch.setenv("HYPERSMART_MICROSTRUCTURE_GATE", "1")
    # LONG voulu à 100 mais le carnet est lourd côté ask -> microprice tombe sous 100
    r = microstructure_entry_gate(coin="MON", side="LONG", intended_price=100.0,
                                  bid=99.5, ask=100.0, bid_size=50, ask_size=5000, base_min_edge_bps=28, max_micro_gap_bps=5.0)
    assert r["applied"] is True
    assert r["allowed"] is False and r["reason"] == "MICROPRICE_ALREADY_ADVERSE"


def test_toxicity_raises_required_edge(monkeypatch):
    _reset()
    monkeypatch.setenv("HYPERSMART_MICROSTRUCTURE_GATE", "1")
    # on enregistre plusieurs fills adverses sur MON -> toxicité monte
    for _ in range(5):
        record_fill_markout("MON", "LONG", 100.0, 99.7)   # prix baisse après entrée LONG = adverse
    r = microstructure_entry_gate(coin="MON", side="LONG", intended_price=100.0,
                                  bid=99.95, ask=100.05, bid_size=500, ask_size=500, base_min_edge_bps=28)
    assert r["toxicity_bps"] > 0
    assert r["min_edge_required_bps"] > 28    # edge requis relevé sur marché toxique


def test_clean_market_passes(monkeypatch):
    _reset()
    monkeypatch.setenv("HYPERSMART_MICROSTRUCTURE_GATE", "1")
    r = microstructure_entry_gate(coin="BTC", side="LONG", intended_price=100.0,
                                  bid=99.98, ask=100.02, bid_size=600, ask_size=400, base_min_edge_bps=28)
    assert r["allowed"] is True and r["reason"] == "MICROSTRUCTURE_OK"
