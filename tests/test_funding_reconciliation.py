"""Réconciliation funding multi-sources — divergence aberrante écartée, dict propre pour l'arb."""
from __future__ import annotations

from hl_observer.market.funding_reconciliation import reconcilier


def test_sources_coherentes_toutes_ok():
    r = reconcilier({"HL": 0.125, "Binance": 0.130, "Bybit": 0.120})
    assert set(r["ok"]) == {"HL", "Binance", "Bybit"}
    assert r["mediane"] == 0.125 and r["dispersion"] > 0


def test_source_aberrante_ecartee():
    r = reconcilier({"HL": 0.125, "Binance": 0.130, "Cassee": 50.0})   # 50 bps/h = cassée
    assert "Cassee" in r["ecartes"] and "Cassee" not in r["ok"]
    assert set(r["ok"]) == {"HL", "Binance"}


def test_funding_absent_ecarte():
    r = reconcilier({"HL": 0.125, "X": None})
    assert r["ecartes"]["X"] == "funding_absent" and r["ok"] == {"HL": 0.125}
