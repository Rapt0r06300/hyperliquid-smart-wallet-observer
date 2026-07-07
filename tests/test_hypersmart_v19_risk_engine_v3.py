from __future__ import annotations

from hl_observer.risk.risk_engine_v3 import (
    EntryCostGuardConfig,
    SessionEntryRiskContext,
    evaluate_entry_cost_guard,
    evaluate_v19_risk_gates,
    format_v19_risk_decision,
    quarantine_suggestions_from_breakdowns,
)


def test_v19_risk_engine_blocks_new_entries_after_large_loss_and_stale_edges():
    decision = evaluate_v19_risk_gates(
        net_pnl_usdc=-8.5,
        total_decisions=10,
        accepted=4,
        negative_events=4,
        positive_events=0,
        fee_drag_ratio=0.5,
        stale_reason_count=6,
        edge_negative_count=3,
        edge_sentinel_count=2,
        orphan_close_count=2,
        profit_factor_net=0.1,
        consecutive_losses=4,
    )

    assert not decision.allow_new_entries
    assert decision.protection_mode
    assert "SESSION_LOSS_HALT" in decision.blocking_codes
    assert "STALE_SIGNALS_DOMINATE" in decision.blocking_codes
    text = format_v19_risk_decision(decision)
    assert "paper_simulation_only=true" in text
    assert "execution=forbidden" in text


def test_v19_risk_engine_allows_when_metrics_are_healthy():
    decision = evaluate_v19_risk_gates(
        net_pnl_usdc=2.0,
        total_decisions=20,
        accepted=8,
        negative_events=2,
        positive_events=6,
        fee_drag_ratio=0.05,
        stale_reason_count=1,
        edge_negative_count=1,
        edge_sentinel_count=0,
        orphan_close_count=0,
        profit_factor_net=1.5,
    )

    assert decision.allow_new_entries
    assert not decision.protection_mode
    assert decision.blocking_codes == ()
    text = format_v19_risk_decision(decision)
    assert "SESSION_LOSS_HALT: OK" in text
    assert "net_pnl_usdc=2.000000 > -5.000000" in text


def test_v19_quarantine_suggestions_rank_negative_buckets():
    suggestions = quarantine_suggestions_from_breakdowns(
        {"BTC": 1.0, "HYPE": -4.2, "ETH": -0.3},
        {"w1": -2.0, "w2": 3.0},
        {"PAPER_OPEN": -1.0},
    )

    assert suggestions["coins"][0]["key"] == "HYPE"
    assert suggestions["wallets"][0]["key"] == "w1"
    assert suggestions["actions"][0]["key"] == "PAPER_OPEN"


def test_v23_entry_cost_guard_blocks_micro_trade_when_fee_drag_is_high():
    decision = evaluate_entry_cost_guard(
        coin="BTC-USD",
        wallet="0xabc",
        notional_usdt=12.0,
        edge_net_bps=22.0,
        context=SessionEntryRiskContext(
            net_pnl_usdc=-0.3,
            fee_drag_ratio=0.52,
            consecutive_losses=4,
            top_losing_coins=(("BTC-USD", -1.2),),
        ),
        config=EntryCostGuardConfig(),
    )

    assert decision.accepted is False
    assert "FEE_DRAG_GUARD_ACTIVE" in decision.reason_codes
    assert "NO_MICRO_TRADE_NOTIONAL" in decision.reason_codes
    assert "ENTRY_EDGE_BELOW_SESSION_REQUIREMENT" in decision.reason_codes
    assert decision.required_min_notional_usdt == 40.0
    assert decision.required_min_edge_bps == 50.0
    assert decision.as_dict()["real_execution"] is False


def test_v23_entry_cost_guard_allows_strong_signal_despite_guard_context():
    decision = evaluate_entry_cost_guard(
        coin="HYPE",
        wallet="0xabc",
        notional_usdt=60.0,
        edge_net_bps=70.0,
        context=SessionEntryRiskContext(fee_drag_ratio=0.52, consecutive_losses=4),
        config=EntryCostGuardConfig(),
    )

    assert decision.accepted is True
    assert "FEE_DRAG_GUARD_ACTIVE" in decision.reason_codes
    assert "LOSS_STREAK_REQUIRES_HIGHER_EDGE" in decision.reason_codes
