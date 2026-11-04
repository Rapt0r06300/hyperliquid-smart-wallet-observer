from hl_observer.ui.economic_writer import ledger_economic_payload


def test_missing_cost_is_unknown_not_zero():
    result = ledger_economic_payload({"net_pnl_usdc": 1.0, "fee_cost_usdc": 0.1})
    assert result["status"] == "UNMEASURABLE"
    assert "spread_cost_usdc" in result["unknown_costs"]
    assert "slippage_cost_usdc" in result["unknown_costs"]


def test_complete_ledger_costs_are_exposed():
    result = ledger_economic_payload({
        "net_pnl_usdc": 1.0,
        "fee_cost_usdc": 0.1,
        "spread_cost_usdc": 0.2,
        "slippage_cost_usdc": 0.3,
        "latency_cost_usdc": 0.0,
    })
    assert result["status"] == "PROVEN"
    assert result["costs"]["latency_cost_usdc"] == 0.0
