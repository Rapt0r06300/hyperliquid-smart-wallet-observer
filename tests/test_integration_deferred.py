"""A7: matérialisation triangulaire paper (gated) + sonde HIP-4 read-only."""

from __future__ import annotations

from hl_observer.arbitrage.triangular_graph import TriangularEdge
from hl_observer.integration.deferred_features import (
    hip4_observation_signal, parse_hip4_outcome, triangular_paper_candidates,
)


def _edges():
    return [TriangularEdge("USDC", "HYPE", 0.01), TriangularEdge("HYPE", "BTC", 0.001), TriangularEdge("BTC", "USDC", 101_500)]


def test_triangular_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_TRIANGULAR_PAPER", raising=False)
    assert triangular_paper_candidates(_edges())["reason"] == "TRIANGULAR_PAPER_OFF"


def test_triangular_produces_paper_candidates_when_on(monkeypatch):
    monkeypatch.setenv("HYPERSMART_TRIANGULAR_PAPER", "1")
    out = triangular_paper_candidates(_edges(), min_net_edge_bps=1.0)
    assert out["reason"] == "OK"
    for c in out["candidates"]:
        assert c["real_execution"] is False and c["type"] == "TRIANGULAR_ARB"


def test_hip4_parser_valid_and_invalid():
    ok = parse_hip4_outcome({"name": "BTC>100k", "yes_price": 0.6, "no_price": 0.45})
    assert ok["valid"] is True and ok["coherence_gap"] == 0.05 and ok["execution"] == "forbidden"
    assert parse_hip4_outcome({"yes_price": "x"})["reason"] == "MISSING_PRICES"
    assert parse_hip4_outcome({"yes_price": 1.5, "no_price": 0.1})["reason"] == "PRICES_OUT_OF_RANGE"
    assert parse_hip4_outcome("nope")["reason"] == "INVALID_SHAPE"


def test_hip4_observation_flags_incoherent_markets():
    markets = [
        {"name": "A", "yes_price": 0.5, "no_price": 0.5},   # cohérent
        {"name": "B", "yes_price": 0.7, "no_price": 0.5},   # somme 1.2, écart 0.2
    ]
    sig = hip4_observation_signal(markets, min_gap=0.02)
    assert sig["observed"] == 2 and sig["incoherent"] == 1
    assert sig["flagged"][0]["market"] == "B" and sig["read_only"] is True
