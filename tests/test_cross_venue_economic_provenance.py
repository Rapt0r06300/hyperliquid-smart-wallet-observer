from __future__ import annotations

from hl_observer.backtesting.cross_venue_certified import FOUR_FILL_CONTRACT_VERSION, SOURCE_MODE
from hl_observer.simulation.economic_objective import evaluate_objective


def _segment(net, gross, char, *, oos=False, forward=False):
    return {"gross_pnl_usd": gross, "fees_usd": 0.1, "spread_cost_usd": 0.1, "slippage_cost_usd": 0.1, "latency_cost_usd": 0.1, "net_pnl_usd": net, "sample_count": 2, "liquidatable_net": True, "duplicate_trade_ids": 0, "trade_ids_count": 2, "trade_ids_sha256": char * 64, "no_lookahead": oos, "post_freeze": forward}


def _proof(meta):
    return {
        "family": "cross_venue_dislocation_v2", "paper_read_only": True, "real_execution": False,
        "starting_capital_usd": 1000.0, "parameters_frozen": True,
        "opened_positions": 4, "closed_positions": 4,
        "gross_pnl_usd": 5.8, "fees_usd": 0.5, "spread_cost_usd": 0.4, "slippage_cost_usd": 0.3, "latency_cost_usd": 0.2, "net_pnl_usd": 4.4,
        "liquidatable_net": True, "all_positions_two_leg_closed": True,
        "duplicate_trade_ids": 0, "trade_ids_count": 4, "trade_ids_sha256": "a" * 64,
        "period": {"collection_meta": meta},
        "oos": _segment(2.2, 2.6, "b", oos=True),
        "forward": _segment(2.2, 2.6, "c", forward=True),
        "placebos": {"beaten": True},
    }


def _certified_meta():
    return {"source_mode": SOURCE_MODE, "certified_snapshots": 10, "mapping_verified": True, "skew_verified": True, "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION}


def test_cross_venue_certified_atomic_provenance_peut_seule_etre_eligible():
    result = evaluate_objective(_proof(_certified_meta()))
    assert result["objective_status"] == "ATTEINT"
    assert result["eligible_net_pnl_usd"] == 4.4


def test_ancien_atomic_sans_mapping_ni_skew_est_explicitement_refuse():
    result = evaluate_objective(_proof({"source_mode": "ATOMIC_FOUR_SIDE_BOOK", "valid_snapshots": 1000}))
    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "CROSS_VENUE_CERTIFIED_ATOMIC_SOURCE_MISSING" in result["objective_reasons"]
    assert "CROSS_VENUE_MAPPING_PROOF_MISSING" in result["objective_reasons"]
    assert "CROSS_VENUE_SKEW_PROOF_MISSING" in result["objective_reasons"]
    assert "CROSS_VENUE_FOUR_FILL_CONTRACT_MISSING" in result["objective_reasons"]
