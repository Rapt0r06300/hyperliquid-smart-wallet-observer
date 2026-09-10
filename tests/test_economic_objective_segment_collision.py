from __future__ import annotations

from hl_observer.simulation.economic_objective import evaluate_objective


def _segment(*, trade_hash: str, no_lookahead: bool = False, post_freeze: bool = False):
    return {
        "gross_pnl_usd": 2.8,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": 2.4,
        "sample_count": 2,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 2,
        "trade_ids_sha256": trade_hash,
        "no_lookahead": no_lookahead,
        "post_freeze": post_freeze,
    }


def test_objective_rejects_oos_forward_trade_identity_collision():
    shared_hash = "b" * 64
    evidence = {
        "family": "copy_vault",
        "paper_read_only": True,
        "real_execution": False,
        "starting_capital_usd": 1000.0,
        "parameters_frozen": True,
        "opened_positions": 4,
        "closed_positions": 4,
        "gross_pnl_usd": 6.0,
        "fees_usd": 0.5,
        "spread_cost_usd": 0.4,
        "slippage_cost_usd": 0.3,
        "latency_cost_usd": 0.2,
        "net_pnl_usd": 4.6,
        "LIQUIDATABLE_NET": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 4,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(trade_hash=shared_hash, no_lookahead=True),
        "forward": _segment(trade_hash=shared_hash, post_freeze=True),
        "placebos": {"beaten": True},
        "vault_generalization": {"sample_count": 20, "net_bps": 3.0},
    }

    result = evaluate_objective(evidence)

    assert result["objective_status"] == "NON_ATTEINT"
    assert result["eligible_net_pnl_usd"] is None
    assert "OOS_FORWARD_TRADE_IDENTITY_COLLISION" in result["objective_reasons"]
