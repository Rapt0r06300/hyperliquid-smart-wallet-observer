"""GAP: grid cappé anti-martingale + orphelins funding_poller/latence + loader bulk."""

from __future__ import annotations

# ordre d'import: amorce le paquet copy_wallet avant copy_mode (cycle préexistant)
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401
from hl_observer.copy_mode.copy_latency_profiler import CopyLatencyProfile
from hl_observer.sources.bulk_history import FakeBulkHistory, coverage_report, load_many_wallets
from hl_observer.funding.funding_poller import parse_meta_and_asset_ctxs
from hl_observer.reports.latency_benchmark_report import build_latency_benchmark_report
from hl_observer.strategies.grid_paper import build_grid, grid_paper_enabled, validate_no_martingale


def test_grid_is_bounded_and_never_martingale():
    g = build_grid(mid_price=100.0, side="LONG", levels=10, base_size_usdt=10.0, max_reentries=5, max_total_usdt=60.0)
    assert g["ok"] is True
    assert g["level_count"] <= 5                        # cap re-entrées
    assert g["total_notional_usdt"] <= 60.0             # cap exposition
    assert validate_no_martingale(g) is True           # tailles non croissantes
    # LONG achète sous le mid
    assert all(l["price"] < 100.0 for l in g["levels"])
    assert g["real_execution"] is False


def test_grid_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_GRID_PAPER", raising=False)
    assert grid_paper_enabled() is False


def test_funding_poller_parses_meta_ctxs_and_rejects_garbage():
    payload = [{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{"funding": "0.0005"}, {"funding": "-0.0002"}]]
    out = parse_meta_and_asset_ctxs(payload)
    assert out == [("BTC", 0.0005), ("ETH", -0.0002)]
    assert parse_meta_and_asset_ctxs("garbage") == []   # forme inattendue → vide honnête


def test_latency_benchmark_report_aggregates():
    profiles = [
        CopyLatencyProfile(leader_to_observed_ms=100, observed_to_decision_ms=50, total_ms=150, warning=None),
        CopyLatencyProfile(leader_to_observed_ms=800, observed_to_decision_ms=200, total_ms=1000, warning="SLOW"),
    ]
    rep = build_latency_benchmark_report(profiles)
    assert rep["samples"] == 2 and rep["max_total_ms"] == 1000 and rep["warning_count"] == 1


def test_bulk_history_loads_and_filters_by_window():
    src = FakeBulkHistory(fills={"0xA": [{"ts_ms": 100}, {"ts_ms": 5000}, {"ts_ms": 9000}]})
    loaded = load_many_wallets(src, ["0xA", "0xB"], start_ms=1000, end_ms=8000)
    assert len(loaded["0xA"]) == 1          # seul ts=5000 est dans la fenêtre
    assert loaded["0xB"] == []
    cov = coverage_report(loaded)
    assert cov["wallets"] == 2 and cov["with_data"] == 1 and "0xB" in cov["empty"]
