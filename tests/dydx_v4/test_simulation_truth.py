from __future__ import annotations

from hyper_smart_observer.dydx_v4.simulation_truth import summarize_truth


def test_simulation_truth_summarizes_counts_and_sources() -> None:
    rows = [
        {"event_type": "DECISION_V2", "action": "OPEN_REDUCED"},
        {"event_type": "PAPER_OPEN", "data_source": "orderbook_real", "size": 50},
        {"event_type": "PAPER_OPEN", "data_source": "fallback_mark", "size": 10},
        {"event_type": "PAPER_CLOSE", "data_source": "orderbook_real", "net_pnl_usdc": 4, "gross_pnl_usdc": 5, "fees_usdc": 1},
        {"event_type": "NO_TRADE", "reason": "TEST_REASON"},
    ]

    summary = summarize_truth(rows)

    assert summary["paper_open_count"] == 2
    assert summary["paper_close_count"] == 1
    assert summary["open_notional_usdc"] == 60
    assert summary["net_pnl_usdc"] == 4
    assert summary["fallback_or_demo_open_share"] == 0.5
    assert summary["decision_v2_actions"]["OPEN_REDUCED"] == 1
    assert summary["top_no_trade_reasons"]["TEST_REASON"] == 1
